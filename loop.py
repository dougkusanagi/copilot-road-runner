"""Loop observe → decide → act → verify → repeat (MVP).

Ordem de decisão (barata primeiro):
  1. deterministic tools (open/focus/type por intenção: notepad, calc, browser)
  2. Windows UI Automation (só janela ativa, formato compacto)
  3. ActionScorer simples (candidates + threshold 0.80 → executa, senão VLM)
  4. VLM SÓ como grounding (screenshot + "locate X" → {x,y} 0..1)
Sem planner grande no MVP.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import psutil

import safety
from actions import execute
from obs import downscale_for_vlm, take_screenshot
from schemas import Action, Decision
from scorer import SimpleScorer, build_candidates
from tools import click_element
from uia import active_window_snapshot, snapshot

LOG = Path("run.jsonl")
_scorer = SimpleScorer()

NOTEPAD_WORDS = ["notepad", "bloco de notas"]
CALC_WORDS = ["calculadora", "calculator"]
BROWSER_WORDS = ["browser", "navegador", "edge", "chrome", "brave", "busque", "buscar",
                 "pesquise", "search", "google"]
BROWSER_TITLES = ["edge", "chrome", "brave", "google", "nova guia", "new tab"]
FOLLOW_WORDS = ["clique", "click", "resultado", "result", "primeiro", "link"]


def _log(obj: dict) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _has_any(ins: str, words: list[str]) -> bool:
    ins = ins.lower()
    return any(w in ins for w in words)


def _extract_text_to_type(instruction: str) -> str:
    m = re.search(r"(?:escreva|escrever|write|digite|digitar|type)\s+[\"']?(.+?)[\"']?$",
                  instruction, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_digit(instruction: str) -> str:
    m = re.search(r"\d", instruction)
    return m.group(0) if m else ""


def _extract_search_query(instruction: str) -> str:
    m = re.search(r"(?:busque|buscar|pesquise|pesquisar|search|procure)\s+[\"']?(.+?)[\"']?$",
                  instruction, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# --- fluxos determinísticos (steps fixos, sem IA) -----------------------------
def _focused(words: list[str]) -> bool:
    from uia import foreground_title

    fg = foreground_title().lower()
    return any(w in fg for w in words)


def _deterministic(step: int, instruction: str, ctx: dict) -> Action | None:
    if _has_any(instruction, NOTEPAD_WORDS):
        if step == 0:
            return Action(type="open", target="notepad")
        if step == 1:
            return Action(type="focus", target="bloco de notas||notepad")
        if ctx.get("typed"):
            return Action(type="done")
        if step == 2:
            # Win11 = multi-tab: abre aba nova p/ nunca digitar em doc do usuário
            return Action(type="hotkey", key="ctrl+n")
        if step >= 3:
            text = _extract_text_to_type(instruction)
            if text:
                return Action(type="type", text=text)
            return None  # sem texto claro → cai p/ UIA/VLM
        return None
    if _has_any(instruction, CALC_WORDS):
        if step == 0:
            return Action(type="open", target="calc")
        return None  # resto via UIA (Teste 2)
    if _has_any(instruction, BROWSER_WORDS):
        # máquina de estágios (ctx), não steps: nunca digita sem o browser focado.
        st = ctx.get("bstage", 0)
        if st == 0:
            if step == 0:
                ctx["bstage"] = 1
                return Action(type="open", target="msedge")
            return None
        if not _focused(BROWSER_TITLES):
            n = ctx.get("bfocus", 0)
            if n < 2:
                ctx["bfocus"] = n + 1
                return Action(type="focus", target="edge||chrome||brave")
            raise RuntimeError("navegador não abriu/não focou; abortando "
                               "para não atuar na janela errada.")
        if st == 1:
            ctx["bstage"] = 2
            return Action(type="hotkey", key="ctrl+l")
        if st == 2:
            from urllib.parse import quote_plus

            query = _extract_search_query(instruction)
            text = query or instruction
            if not text.startswith("http"):
                text = "https://www.google.com/search?q=" + quote_plus(text)
            ctx["bstage"] = 3
            return Action(type="type", text=text)
        if st == 3:
            ctx["bstage"] = 4
            return Action(type="hotkey", key="enter")
        # st >= 4: busca submetida. Sem follow-up explícito → done;
        # com "clique no resultado..." → segue p/ UIA/scorer/VLM.
        if _has_any(instruction, FOLLOW_WORDS):
            return None
        return Action(type="done")
    return None


# --- conclusão por verificação (sem LLM) --------------------------------------
def _done_by_verify(instruction: str, ctx: dict) -> tuple[bool, str]:
    """Checa objetivo cumprido via UIA. Só p/ testes determinísticos."""
    if _has_any(instruction, CALC_WORDS):
        digit = _extract_digit(instruction)
        if not digit:
            return False, ""
        for el in snapshot():
            if el.automation_id == "CalculatorResults" and digit in (el.name or ""):
                return True, f"calculator display = {digit}"
        return False, ""
    if _has_any(instruction, NOTEPAD_WORDS):
        text = _extract_text_to_type(instruction)
        if not text:
            return False, ""
        needle = text[:20].lower()
        for el in snapshot():
            if needle and needle in (el.name or "").lower():
                return True, "notepad text verified"
        return False, ""
    if _has_any(instruction, BROWSER_WORDS):
        if ctx.get("bstage", 0) >= 4 and _focused(BROWSER_TITLES):
            return True, "browser search submitted"
        return False, ""
    return False, ""


# --- decide -------------------------------------------------------------------
def decide(instruction: str, step: int, ctx: dict, cfg: dict) -> tuple[Decision, dict]:
    t: dict = {}
    t0 = time.perf_counter()
    det = _deterministic(step, instruction, ctx)
    t["tool_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if det is not None:
        src = "deterministic"
        return Decision(action=det, source=src, confidence=0.99,
                        reason="deterministic tool"), t

    t1 = time.perf_counter()
    items, title, wrect = active_window_snapshot()
    t["uia_ms"] = round((time.perf_counter() - t1) * 1000, 1)
    t["uia_title"] = title
    t["uia_count"] = len(items)

    t2 = time.perf_counter()
    cands = build_candidates(items)
    scored = _scorer.score(instruction, title, cands)
    t["scorer_ms"] = round((time.perf_counter() - t2) * 1000, 1)
    top = scored[0]
    t["scorer_top"] = top.candidate.label
    t["scorer_conf"] = top.confidence

    threshold = float(cfg.get("scorer_threshold", 0.8))
    if top.confidence >= threshold and top.candidate.kind == "click":
        b = top.candidate.bounds or [0, 0, 0, 0]
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        # clique precisa cair DENTRO da janela ativa (mata rects fantasmas)
        if wrect is not None and not (wrect[0] <= cx <= wrect[2]
                                      and wrect[1] <= cy <= wrect[3]):
            t["scorer_top"] = f"{top.candidate.label} (fora da janela; ignorado)"
        else:
            return Decision(action=Action(type="click", x=cx, y=cy), source="scorer",
                            confidence=top.confidence,
                            reason=f'scorer {top.candidate.label}'), t

    # VLM: só grounding
    if ctx.get("no_vlm"):
        raise RuntimeError(f"top={top.candidate.label} conf={top.confidence:.2f} "
                           f"< {threshold} e --no-vlm ativo.")
    from vlm import LMStudioVisionModel, check_server

    t3 = time.perf_counter()
    status = check_server(cfg.get("base_url", "http://127.0.0.1:1234/v1"))
    if not status.get("ok"):
        raise RuntimeError(f"top={top.candidate.label} conf={top.confidence:.2f} "
                           f"< {threshold} e servidor offline: {status.get('error')}. "
                           "Suba o modelo vision ou rode com --no-vlm.")
    from obs import LAST_PNG

    b64, _ = downscale_for_vlm(LAST_PNG, max_width=int(cfg.get("screenshot_max_width", 1280)))
    _, real = take_screenshot()
    vm = LMStudioVisionModel(base_url=cfg["base_url"], model=cfg.get("vision_model", "MAI-UI-2B"))
    target = _extract_text_to_type(instruction) or instruction
    res = vm.locate_sync(b64, f'"{target}" button/element')
    t["vision_ms"] = round((time.perf_counter() - t3) * 1000, 1)
    t["vision_calls"] = 1
    if res.x < 0:
        raise RuntimeError("VLM não encontrou o elemento (x=-1).")
    return Decision(action=vm.to_click(res, real), source="vlm",
                    confidence=res.confidence, reason="vision grounding"), t


# --- verify -------------------------------------------------------------------
def verify(action: Action, instruction: str, cfg: dict) -> tuple[bool, str]:
    """Espera curta + re-observa. Best-effort, nunca usa modelo."""
    time.sleep(max(0, int(cfg.get("verify_wait_ms", 500))) / 1000.0)
    if safety.stop_requested():
        return False, "aborted"
    if _has_any(instruction, CALC_WORDS):
        digit = _extract_digit(instruction)
        for el in snapshot():
            if el.automation_id == "CalculatorResults":
                ok = bool(digit) and digit in (el.name or "")
                return ok, f"calculator display = {el.name!r}"
        return False, "calc results not found"
    if _has_any(instruction, NOTEPAD_WORDS):
        from uia import foreground_title as _fg

        fg = _fg()
        ok = "bloco de notas" in fg.lower() or "notepad" in fg.lower()
        if not ok:
            return False, f"foco fora do notepad: active={fg!r} (retry)"
        text = _extract_text_to_type(instruction)
        needle = text[:20].lower() if text else ""
        if needle:
            for el in snapshot():
                if needle in (el.name or "").lower():
                    return True, "notepad text verified"
        return True, f"typed, active={fg!r} (texto não exposto na UIA)"
    if _has_any(instruction, BROWSER_WORDS):
        from uia import foreground_title as _fg

        fg = _fg()
        ok = _focused(BROWSER_TITLES)
        return ok, f"browser active={fg!r}" if ok else f"foco fora do browser: active={fg!r}"
    items, title, _ = active_window_snapshot()
    return bool(title), f"active={title!r}"


def _key(a: Action) -> str:
    return f"{a.type}:{a.x},{a.y}:{a.text}:{a.key}:{a.target}"


# --- run ----------------------------------------------------------------------
def run(instruction: str, cfg: dict) -> dict:
    max_steps = int(cfg.get("max_steps", 20))
    print(f"Task: {instruction}")
    print("Stop: Ctrl+Alt+Esc (ou ESC) | Ctrl+C no terminal.")
    safety.start()
    try:
        import overlay as _ov

        ov_on = _ov.start()
    except Exception:
        ov_on = False
    print(f"Overlay de controle: {'ON (borda azul)' if ov_on else 'OFF (tkinter indisponível)'}")
    if LOG.exists():
        LOG.unlink()

    ctx: dict = {"no_vlm": bool(cfg.get("no_vlm", False))}
    metrics = {"tool_ms": 0.0, "uia_ms": 0.0, "scorer_ms": 0.0, "vision_ms": 0.0,
               "execution_ms": 0.0, "vision_calls": 0, "steps": 0}
    history: list[str] = []
    forced_vision = False
    n = 0
    total0 = time.perf_counter()
    result = "stopped"

    def emit(layer: str, msg: str, ms) -> None:
        nonlocal n
        n += 1
        print(f"[{n}] {layer:<7} {msg} {ms}" if ms != "" else f"[{n}] {layer:<7} {msg}")

    try:
        for step in range(max_steps):
            if safety.stop_requested():
                _log({"step": step, "event": "aborted"})
                result = "aborted"
                break
            s0 = time.perf_counter()
            path, real_size = take_screenshot()

            done, note = _done_by_verify(instruction, ctx)
            if done:
                emit("VERIFY", note, "")
                result = "done"
                break

            try:
                dec, tm = decide(instruction, step, ctx, cfg)
            except RuntimeError as e:
                print(f"PARADO step {step}: {e}")
                _log({"step": step, "event": "stuck", "error": str(e)})
                result = "stuck"
                break

            metrics["tool_ms"] += tm.get("tool_ms", 0)
            metrics["uia_ms"] += tm.get("uia_ms", 0)
            metrics["scorer_ms"] += tm.get("scorer_ms", 0)
            metrics["vision_ms"] += tm.get("vision_ms", 0)
            metrics["vision_calls"] += tm.get("vision_calls", 0)

            if dec.source == "deterministic":
                a = dec.action
                arg = a.target or a.text or a.key or ""
                emit("TOOL", f'{a.type}("{arg}")', f'{tm.get("tool_ms", 0):.0f} ms')
            else:
                emit("UIA", f'found {tm.get("uia_count", 0)} ("{tm.get("uia_title", "")}")',
                     f'{tm.get("uia_ms", 0):.0f} ms')
                if dec.source == "scorer":
                    emit("SCORER", f'{tm.get("scorer_top")}',
                         f'{tm.get("scorer_ms", 0):.0f} ms | confidence {dec.confidence:.2f}')
                else:
                    emit("VLM", f'grounding ({dec.reason})',
                         f'{tm.get("vision_ms", 0):.0f} ms | confidence {dec.confidence:.2f}')

            # anti-loop: mesma ação 3× → força vision 1×; se persistir → stop
            k = _key(dec.action)
            history.append(k)
            if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
                if not forced_vision and not ctx.get("no_vlm"):
                    print("mesma acao 3x -> forcando vision fallback 1x")
                    forced_vision = True
                    history.clear()
                    continue
                print("loop persistente -> stop.")
                _log({"step": step, "event": "loop"})
                result = "loop"
                break

            e0 = time.perf_counter()
            # fecha TOCTOU: toast pode roubar o foco entre decide e execute;
            # reafirma o foco imediatamente antes de digitar.
            if dec.action.type == "type" and _has_any(instruction, NOTEPAD_WORDS):
                from tools import focus_window as _fw
                _fw("bloco de notas||notepad", timeout=3.0)
            if dec.action.type == "type" and _has_any(instruction, BROWSER_WORDS):
                from tools import focus_window as _fw
                _fw("edge||chrome||brave", timeout=3.0)
            try:
                desc = execute(dec.action)
            except (ValueError, AssertionError) as e:
                # ex: clique fora da tela → para com mensagem, nunca clica no escuro
                print(f"PARADO step {step}: ação recusada: {e}")
                _log({"step": step, "event": "refused", "error": str(e)})
                result = "stuck"
                break
            exec_ms = (time.perf_counter() - e0) * 1000
            metrics["execution_ms"] += exec_ms
            emit("EXEC", desc, f"{exec_ms:.0f} ms")

            if dec.action.type == "type" and _has_any(instruction, NOTEPAD_WORDS):
                ctx["typed"] = True
            if dec.action.type == "done":
                result = "done"
                break

            ok, vnote = verify(dec.action, instruction, cfg)
            emit("VERIFY", vnote, "")
            if dec.action.type == "type" and _has_any(instruction, NOTEPAD_WORDS):
                ctx["typed"] = ok or ctx.get("typed", False)
            metrics["steps"] += 1
            _log({"step": step, "source": dec.source, "confidence": dec.confidence,
                  "reason": dec.reason, "did": desc, "action": dec.action.model_dump(),
                  "verify": vnote, "timings": tm,
                  "cpu": psutil.cpu_percent(interval=None),
                  "mem": round(psutil.virtual_memory().percent, 1)})
            time.sleep(0.3)
        else:
            result = "max_steps"
    except KeyboardInterrupt:
        result = "aborted"
        print("\nabortado via Ctrl+C.")
    finally:
        safety.stop()
        try:
            import overlay as _ov

            _ov.stop()
        except Exception:
            pass

    total_ms = (time.perf_counter() - total0) * 1000
    print(f"\n{result.upper()}")
    print(f"Total: {total_ms / 1000:.1f}s")
    summary = {"test": instruction, "result": result, "steps": metrics["steps"],
               "vision_calls": metrics["vision_calls"],
               "total_s": round(total_ms / 1000, 1), "metrics_ms": {
                   "tool": round(metrics["tool_ms"], 1), "uia": round(metrics["uia_ms"], 1),
                   "scorer": round(metrics["scorer_ms"], 1),
                   "vision": round(metrics["vision_ms"], 1),
                   "exec": round(metrics["execution_ms"], 1)}}
    print(f"log em {LOG}")
    return summary
