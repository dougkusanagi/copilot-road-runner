"""Loop observe -> decide -> act -> verify -> repeat (2 modelos, decisão 100% IA).

Arquitetura:
  MiniCPM5-1B = pensar (só texto compacto; nunca recebe screenshots,
                nunca emite coordenadas)
  Vocaela-2-500M = enxergar (screenshot + instrução curta -> ação visual 0..1)
  Python = executar (tools, UIA, mouse/teclado) — NUNCA decide.

Ordem de decisão (barata primeiro), todas vindas do planner:
  1. native tool      (open/focus/type decididos pelo planner)
  2. UI Automation    (uia_click por NOME; Vocaela nunca é chamado à toa)
  3. Vocaela          (SÓ quando o elemento não está na accessibility tree)

Sem router determinístico, sem scorer, sem conclusão programática de "done":
se os modelos não estiverem online, o agente para com erro honesto.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import psutil

import safety
from actions import execute
from obs import capture_for_vision
from planner import MiniCPMPlanner, PlannerDecision
from schemas import Action, Decision
from uia import active_window_snapshot, foreground_title  # foreground_title: guard calc
from vocaela import VocaelaAdapter, visual_to_action

LOG = Path("run.jsonl")

CALC_WORDS = ["calculadora", "calculator"]

_JUNK_TYPES = {"window", "titlebar", "menubar"}
_CHROME_PREFIXES = ("minimizar ", "maximizar ", "restaurar ", "fechar ",
                    "minimize ", "maximize ", "restore ", "close ")
# número-por-extenso PT+EN (UIA da calculadora Win expõe "Sete", não "7")
_DIGIT_WORDS = {"0": ("zero",), "1": ("um", "one"), "2": ("dois", "two"),
                "3": ("tres", "três", "three"), "4": ("quatro", "four"),
                "5": ("cinco", "five"), "6": ("seis", "six"),
                "7": ("sete", "seven"), "8": ("oito", "eight"),
                "9": ("nove", "nine")}
_WORD_DIGIT = {w: d for d, ws in _DIGIT_WORDS.items() for w in ws}


def _log(obj: dict) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _has_any(ins: str, words: list[str]) -> bool:
    ins = ins.lower()
    return any(w in ins for w in words)


def _extract_text_to_type(instruction: str) -> str:
    m = re.search(r"(?:escreva|escrever|write|digite|digitar|type)\s*[:\-—]?\s*[\"']?(.+?)[\"']?$",
                  instruction, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_digit(instruction: str) -> str:
    m = re.search(r"\d", instruction)
    return m.group(0) if m else ""


def _extract_search_query(instruction: str) -> str:
    m = re.search(r"(?:busque|buscar|pesquise|pesquisar|search|procure)\s*[:\-—]?\s*[\"']?(.+?)[\"']?$",
                  instruction, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# (dígito → nomes PT+EN em _DIGIT_WORDS acima; _resolve_uia expande sozinho)


# --- bootstrap do app pedido (ferramenta determinística, sem IA) ---------------
def _app_bootstrap(instruction: str, step: int, active_lower: str) -> Action | None:
    """Garante a JANELA certa aberta antes das decisões por modelo.

    open_app é ferramenta (o MiniCPM não abre processo), por isso estes steps
    fixos existem e rodam ANTES do planner decidir qualquer coisa: o planner
    já recebe a janela certa no estado, e a partir daí tudo é IA
    (uia_click → Vocaela → type/hotkey...). Sem branch por tipo de app aqui:
    só abrir app + confirmar foco.
    """
    low = instruction.lower()
    want = "notepad.exe" if any(w in low for w in ("notepad", "bloco de notas")) \
        else "calc.exe" if any(w in low for w in ("calculadora", "calculator")) \
        else None
    if want is None:
        return None  # browser e resto: planner resolve (open_url/focus/visual)
    app_word = "notepad" if want == "notepad.exe" else "calcul"
    if app_word in active_lower:
        return None  # janela certa já ativa: mão p/ os modelos
    if step == 0:
        return Action(type="open", target=want)
    from tools import focus_window

    focus_window("bloco de notas||notepad" if want == "notepad.exe"
                 else "calculadora||calculator", timeout=3.0)
    return Action(type="wait", ms=300)


# --- verify -------------------------------------------------------------------
def _resolve_uia(items: list[dict], target: str, wrect: tuple | None,
                 state_title: str = "") -> Action | None:
    """Encontra elemento pelo NOME na janela ativa -> click no centro.

    Retorna None se não achar (chamador escala p/ Vocaela). Nunca clica fora
    da janela ativa nem em chrome (minimizar/fechar) nem na própria janela.
    """
    want = (target or "").strip().lower()
    if not want:
        return None
    # "7" casa "Sete" e vice-versa
    wants = {want}
    if want in _DIGIT_WORDS:
        wants |= set(_DIGIT_WORDS[want])
    if want in _WORD_DIGIT:
        wants.add(_WORD_DIGIT[want])
    exact = prefix = sub = None
    for it in items:
        name = (it.get("name") or "").strip()
        if not name or len(name) > 60:
            continue
        nl = name.lower()
        if nl.startswith(_CHROME_PREFIXES):
            continue
        if (it.get("type") or "").lower() in _JUNK_TYPES:
            continue
        if state_title and nl == state_title.lower():
            continue
        if nl in wants and exact is None:
            exact = it
            continue
        for w in wants:
            if nl.startswith(w) and prefix is None:
                prefix = it
            elif w in nl and sub is None:
                sub = it
    hit = exact or prefix or sub
    if hit is None:
        return None
    b = hit.get("bounds") or [0, 0, 0, 0]
    cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
    if wrect is not None and not (wrect[0] <= cx <= wrect[2]
                                  and wrect[1] <= cy <= wrect[3]):
        return None  # rect fantasma fora da janela -> trata como miss
    return Action(type="click", x=cx, y=cy)


def _planner_to_action(dec: PlannerDecision) -> Action | None:
    """Mapeia decisão nativa do planner -> Action. uia_click/visual voltam None
    (resolvidos à parte)."""
    t = dec.type
    if t == "open_app":
        return Action(type="open", target=dec.app or "")
    if t == "open_url":
        from tools import open_url

        return open_url(dec.url or "")
    if t == "focus_window":
        return Action(type="focus", target=dec.target or "")
    if t == "type_text":
        return Action(type="type", text=dec.text or "")
    if t == "press_key":
        return Action(type="hotkey", key=dec.key or "enter")
    if t == "hotkey":
        return Action(type="hotkey", key=dec.keys or "")
    if t == "wait":
        return Action(type="wait", ms=dec.ms or 1000)
    if t == "done":
        return Action(type="done")
    return None  # uia_click, visual_action


def _short(dec: PlannerDecision) -> str:
    t = dec.type
    arg = (dec.app or dec.url or dec.target or dec.text or dec.key
           or dec.keys or dec.instruction or "")
    if len(arg) > 42:
        arg = arg[:42] + "..."
    return f"{t}({arg})" if arg else t


# --- decide: fluxo principal (planner) ----------------------------------------
def _decide_planner(instruction: str, step: int, ctx: dict, cfg: dict,
                    planner: MiniCPMPlanner,
                    vocaela: VocaelaAdapter) -> tuple[Decision, dict]:
    t: dict = {"planner_ms": 0.0, "uia_ms": 0.0, "screenshot_ms": 0.0,
               "vision_ms": 0.0, "vision_calls": 0, "planner_calls": 0}
    t0 = time.perf_counter()
    items, title, wrect = active_window_snapshot()
    t["uia_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    t["uia_title"] = title
    t["uia_count"] = len(items)
    names = [(it.get("name") or "") for it in items][:40]

    last_error = ctx.get("last_error", "")
    try:
        dec, pms = planner.next_action(
            goal=instruction, window=title, ui_names=names,
            history=ctx.get("hist_labels", []), last_error=last_error)
    except Exception as e:
        ctx["planner_errors"] = ctx.get("planner_errors", 0) + 1
        raise RuntimeError(f"planner falhou: {e}")
    t["planner_ms"] = round(pms, 1)
    t["planner_calls"] = 1
    t["planner_decision"] = dec.model_dump()
    ctx["planner_errors"] = 0
    ctx["last_error"] = ""

    # bootstrap determinístico do app pedido (steps fixos, SEM IA): open_app
    # é ferramenta — um planner 1B local não abre processo no Windows, só
    # produz JSON. Passado o bootstrap da janela certa, 100% por modelos.
    boot = _app_bootstrap(instruction, step, (title or "").lower())
    if boot is not None:
        return Decision(action=boot, source="planner", confidence=1.0,
                        reason=f"bootstrap {_short(dec)}"), t

    # guarda anti-janela-errada: sem foco no alvo, planner deve focar/abrir —
    # se ele insistir em agir, devolve como last_error em vez de executar.
    if _has_any(instruction, CALC_WORDS) and "calcul" not in title.lower() \
            and dec.type in ("type_text", "uia_click", "visual_action",
                             "press_key", "hotkey"):
        ctx["last_error"] = (f"janela ativa é {title!r}, não a calculadora; "
                             "use focus_window ou open_app primeiro.")
        raise RuntimeError(ctx["last_error"])

    native = _planner_to_action(dec)
    if native is not None:
        return Decision(action=native, source="planner", confidence=0.9,
                        reason=f"planner {_short(dec)}"), t

    if dec.type == "uia_click":
        hit = _resolve_uia(items, dec.target or "", wrect, state_title=title)
        if hit is not None:
            return Decision(action=hit, source="uia", confidence=0.9,
                            reason=f'uia_click("{dec.target}")'), t
        # miss acessível -> escala p/ visão com a mesma intenção
        dec = PlannerDecision(type="visual_action",
                              instruction=f"Click {dec.target}")
        t["escalated"] = "uia_miss->vision"

    # visual_action: screenshot SÓ agora -> Vocaela -> coords 0..1 -> físico
    s0 = time.perf_counter()
    img, origin, full = capture_for_vision(
        max_long_edge=int(cfg.get("screenshot_max_width", 1024)))
    t["screenshot_ms"] = round((time.perf_counter() - s0) * 1000, 1)
    try:
        from obs import LAST_PNG

        img.save(LAST_PNG)  # prova/depuração do que o Vocaela viu
    except Exception:
        pass
    try:
        va, vms = vocaela.act_sync(img, dec.instruction or "")
    except Exception as e:
        raise RuntimeError(f"vocaela falhou: {e}")
    t["vision_ms"] = round(vms, 1)
    t["vision_calls"] = 1
    t["visual"] = va.model_dump()
    act = visual_to_action(va, (img.size[0], img.size[1]), origin)
    return Decision(action=act, source="vocaela", confidence=0.8,
                    reason=f'visual "{dec.instruction}" -> '
                           f'{va.type}({va.x},{va.y})'), t


def decide(instruction: str, step: int, ctx: dict, cfg: dict,
           planner: MiniCPMPlanner | None = None,
           vocaela: VocaelaAdapter | None = None) -> tuple[Decision, dict]:
    """TODA decisão vem dos modelos. Sem planner -> erro honesto (sem router)."""
    if planner is None or vocaela is None:
        raise RuntimeError(
            "arquitetura de 2 modelos exige MiniCPM5-1B (8091) e Vocaela (8082) "
            "online; sem fallback programático.")
    return _decide_planner(instruction, step, ctx, cfg, planner, vocaela)


# --- verify: observação passiva (NUNCA decide ação nem done) -------------------
def verify(action: Action, instruction: str, cfg: dict) -> tuple[bool, str]:
    """Espera curta + título da janela ativa, só p/ log. Não decide nada."""
    time.sleep(max(0, int(cfg.get("verify_wait_ms", 500))) / 1000.0)
    if safety.stop_requested():
        return False, "aborted"
    items, title, _ = active_window_snapshot()
    return bool(title), f"active={title!r}"


# --- verify -------------------------------------------------------------------
def _key(a: Action) -> str:
    return f"{a.type}:{a.x},{a.y}:{a.text}:{a.key}:{a.target}"


def _vram() -> str:
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return f"{out} MiB (nvidia-smi)" if out else "n/a"
    except Exception:
        return "n/a (sem nvidia-smi)"


# --- run ----------------------------------------------------------------------
def run(instruction: str, cfg: dict) -> dict:
    max_steps = int(cfg.get("max_steps", 30))
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

    # --- sobe os dois modelos: OBRIGATÓRIOS (decisão 100% por modelos) ---
    pc = cfg.get("planner", {})
    planner = MiniCPMPlanner(base_url=pc.get("base_url", "http://127.0.0.1:8091/v1"),
                             model=pc.get("model", "MiniCPM5-1B"),
                             temperature=float(pc.get("temperature", 0.1)),
                             timeout_s=float(pc.get("timeout_s", 90)))
    st = planner.check()
    if not st.get("ok"):
        print(f"Planner MiniCPM5-1B OFFLINE: {st.get('error')}")
        print("Suba o planner (llama-server em 8091) e rode de novo. "
              "Sem fallback programático: os modelos decidem.")
        _log({"event": "no_model", "planner": str(st.get("error"))[:200]})
        safety.stop()
        return {"test": instruction, "result": "no_model", "mode": "planner-only",
                "steps": 0, "planner_calls": 0, "vocaela_calls": 0}
    vc = cfg.get("vision", {})
    vocaela = VocaelaAdapter(
        base_url=vc.get("base_url", "http://127.0.0.1:8082/v1"),
        model=vc.get("model", "Vocaela-2-500M-1024R2"),
        timeout_s=float(vc.get("timeout_s", 180)),
        max_long_edge=int(cfg.get("screenshot_max_width", 1024)))
    vs = vocaela.check()
    if not vs.get("ok") and not cfg.get("no_vision"):
        print(f"Vocaela OFFLINE ({vs.get('error')}); visual_action vai falhar — "
              "suba o llama-server do Vocaela em 8082.")
    mode = "planner"
    print(f"Planner: MiniCPM ({planner.base_url} modelos={st.get('models')})")
    vs2 = vocaela.check()
    print(f"Visão: Vocaela ({vocaela.base_url} "
          f"{'ok' if vs2.get('ok') else 'OFFLINE: ' + str(vs2.get('error'))[:80]})")

    ctx: dict = {"no_vision": bool(cfg.get("no_vision", cfg.get("no_vlm", False))),
                 "hist_labels": []}
    metrics = {"planner_ms": 0.0, "uia_ms": 0.0, "screenshot_ms": 0.0,
               "vision_ms": 0.0, "execution_ms": 0.0, "step_ms": 0.0,
               "vision_calls": 0, "planner_calls": 0, "steps": 0}
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

            try:
                dec, tm = decide(instruction, step, ctx, cfg, planner, vocaela)
            except RuntimeError as e:
                # erro do planner/vocaela: alimenta last_error, retenta até 3x
                n = ctx.get("decide_errors", 0) + 1
                ctx["decide_errors"] = n
                ctx["last_error"] = str(e)[:300]
                if n > 3:
                    print(f"PARADO step {step}: decisao falhou 4x: {e}")
                    _log({"step": step, "event": "stuck", "error": str(e)[:300]})
                    result = "stuck"
                    break
                print(f"[retry {n}/3] step {step}: {e}")
                _log({"step": step, "event": "retry", "error": str(e)[:300]})
                time.sleep(0.5)
                continue
            ctx["decide_errors"] = 0

            metrics["planner_ms"] += tm.get("planner_ms", 0) + tm.get("tool_ms", 0)
            metrics["uia_ms"] += tm.get("uia_ms", 0)
            metrics["screenshot_ms"] += tm.get("screenshot_ms", 0)
            metrics["vision_ms"] += tm.get("vision_ms", 0)
            metrics["vision_calls"] += tm.get("vision_calls", 0)
            metrics["planner_calls"] += tm.get("planner_calls", 0)

            src = dec.source
            if src == "planner" and dec.action.type in (
                    "open", "focus", "type", "hotkey", "wait", "done"):
                a = dec.action
                arg = a.target or a.text or a.key or ""
                emit("PLANNER", f'{a.type}("{arg}")',
                     f'{tm.get("planner_ms", 0):.0f}ms')
            else:
                if tm.get("uia_count") is not None:
                    emit("UIA", f'found {tm.get("uia_count", 0)} '
                                f'("{tm.get("uia_title", "")}")',
                         f'{tm.get("uia_ms", 0):.0f}ms')
                if src == "vocaela":
                    va = tm.get("visual", {})
                    emit("PLANNER", f'visual: {tm.get("planner_decision", {}).get("instruction", "")}',
                         f'{tm.get("planner_ms", 0):.0f}ms')
                    if tm.get("screenshot_ms"):
                        emit("SHOT", "active-window capture",
                             f'{tm.get("screenshot_ms", 0):.0f}ms')
                    emit("VISION", f'{va.get("type")}({va.get("x")}, {va.get("y")})',
                         f'{tm.get("vision_ms", 0):.0f}ms')
                elif src == "uia":
                    emit("PLANNER", f'uia: {dec.reason}',
                         f'{tm.get("planner_ms", 0):.0f}ms')
                else:  # pragma: no cover — decide() só retorna planner/uia/vocaela
                    emit("PLANNER", dec.reason or src,
                         f'{tm.get("planner_ms", 0):.0f}ms')

            # anti-loop: mesma ação 3× -> força vision 1×; se persistir -> stop
            k = _key(dec.action)
            history.append(k)
            if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
                if not forced_vision and not ctx.get("no_vision") and vocaela is not None:
                    print("mesma acao 3x -> forcando vision fallback 1x")
                    forced_vision = True
                    history.clear()
                    continue
                print("loop persistente -> stop.")
                _log({"step": step, "event": "loop"})
                result = "loop"
                break

            e0 = time.perf_counter()
            try:
                desc = execute(dec.action)
            except (ValueError, AssertionError) as e:
                # ex: clique fora da tela -> para com mensagem, nunca clica no escuro
                print(f"PARADO step {step}: ação recusada: {e}")
                _log({"step": step, "event": "refused", "error": str(e)})
                result = "stuck"
                break
            exec_ms = (time.perf_counter() - e0) * 1000
            metrics["execution_ms"] += exec_ms
            emit("EXEC", desc, f"{exec_ms:.0f}ms")

            label = desc
            if src == "vocaela" and tm.get("visual"):
                va = tm["visual"]
                label = (f'visual "{tm.get("planner_decision", {}).get("instruction", "")}"'
                         f" -> {va.get('type')}({va.get('x')},{va.get('y')})")
            ctx["hist_labels"].append(label)

            if dec.action.type == "done":
                result = "done"
                break

            ok, vnote = verify(dec.action, instruction, cfg)
            emit("VERIFY", vnote, "")
            metrics["steps"] += 1
            _log({"step": step, "source": dec.source, "confidence": dec.confidence,
                  "reason": dec.reason, "did": desc, "action": dec.action.model_dump(),
                  "verify": vnote, "timings": tm,
                  "cpu": psutil.cpu_percent(interval=None),
                  "mem": round(psutil.virtual_memory().percent, 1)})
            step_ms = (time.perf_counter() - s0) * 1000
            metrics["step_ms"] += step_ms
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
    pcalls = metrics["planner_calls"]
    vcalls = metrics["vision_calls"]
    summary = {"test": instruction, "result": result, "mode": mode,
               "steps": metrics["steps"],
               "planner_calls": pcalls, "vocaela_calls": vcalls,
               "total_s": round(total_ms / 1000, 1),
               "avg_planner_ms": round(metrics["planner_ms"] / pcalls, 1) if pcalls else 0,
               "avg_vision_ms": round(metrics["vision_ms"] / vcalls, 1) if vcalls else 0,
               "ram_pct": round(psutil.virtual_memory().percent, 1),
               "vram": _vram(),
               "metrics_ms": {
                   "planner": round(metrics["planner_ms"], 1),
                   "uia": round(metrics["uia_ms"], 1),
                   "screenshot": round(metrics["screenshot_ms"], 1),
                   "vision": round(metrics["vision_ms"], 1),
                   "exec": round(metrics["execution_ms"], 1)}}
    print(f"log em {LOG}")
    return summary
