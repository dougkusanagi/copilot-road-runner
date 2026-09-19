"""Loop observe -> decide -> act -> verify -> repeat (2 modelos).

Arquitetura:
  MiniCPM5-1B = pensar (só texto compacto; nunca recebe screenshots,
                nunca emite coordenadas)
  Vocaela-2-500M = enxergar (screenshot + instrução curta -> ação visual 0..1)
  Python = executar, OBSERVAR e VETAR — nunca escolher a ação.

Ordem de decisão (barata primeiro), todas vindas do planner:
  1. native tool      (open/focus/type decididos pelo planner)
  2. UI Automation    (uia_click por NOME; Vocaela nunca é chamado à toa)
  3. Vocaela          (SÓ quando o elemento não está na accessibility tree)

Guard-rails determinísticos (Python veta/observa, não escolhe):
  - bootstrap da janela do app pedido (open_app é ferramenta; um 1B não
    abre processo) — roda ANTES de gastar uma chamada ao planner;
  - guarda anti-janela-errada e anti-repetição: devolvem `last_error` ao
    planner em vez de executar;
  - veto de coordenada fora da tela/janela (actions/_resolve_uia).

Sem modelos online = erro honesto, sem fallback programático.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import psutil

import safety
import server
from actions import execute
from obs import capture_for_vision
from planner import MiniCPMPlanner, PlannerDecision
from schemas import Action, Decision
from uia import active_window_snapshot, focused_value
from vocaela import VocaelaAdapter, visual_to_action

LOG = Path("run.jsonl")

CALC_WORDS = ("calculadora", "calculator")
MAX_RETRIES = 3  # erros de decisão/tool consecutivos antes de "stuck"

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

# §5.5: controles interativos primeiro (no Edge os 40 primeiros da árvore
# são quase só chrome; o conteúdo web ficava fora do prompt).
_INTERACTIVE_TYPES = {"button", "edit", "hyperlink", "menuitem", "listitem",
                      "tabitem", "checkbox", "radiobutton", "combobox",
                      "spinner", "splitbutton", "treeitem", "thumb", "slider"}


def format_ui_names(items: list[dict], limit: int = 40) -> list[str]:
    """`tipo:nome` p/ o planner, interativos primeiro (puro, testável).

    Ex.: "Button:7", "Edit:Pesquisar". Sem coordenadas (o planner não vê
    a tela). Nomes >60 chars são os mesmos que `_resolve_uia` ignora.
    """
    def label(it: dict) -> str | None:
        name = (it.get("name") or "").strip()
        if not name:
            return None
        ctype = (it.get("type") or "").strip() or "?"
        return f"{ctype}:{name[:60]}"

    ordered = sorted(items, key=lambda it: (
        0 if (it.get("type") or "").strip().lower() in _INTERACTIVE_TYPES else 1))
    out: list[str] = []
    for it in ordered:
        lab = label(it)
        if lab:
            out.append(lab)
        if len(out) >= limit:
            break
    return out


def _log(obj: dict) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _has_any(ins: str, words: tuple[str, ...]) -> bool:
    ins = ins.lower()
    return any(w in ins for w in words)


# --- guard: bootstrap do app pedido (ferramenta determinística, sem IA) --------
def _app_bootstrap(instruction: str, step: int, active_lower: str) -> Action | None:
    """Garante a JANELA certa aberta antes das decisões por modelo.

    open_app é ferramenta (o MiniCPM não abre processo), por isso estes steps
    fixos existem e rodam ANTES do planner: ele já recebe a janela certa no
    estado, e a partir daí tudo é IA. Só abrir app + confirmar foco.
    """
    low = instruction.lower()
    want = "notepad.exe" if any(w in low for w in ("notepad", "bloco de notas")) \
        else "calc.exe" if _has_any(low, CALC_WORDS) \
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


# --- UIA por nome ------------------------------------------------------------
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
    (resolvidos à parte). ValueError das tools (whitelist/URL) sobe ao chamador."""
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
    names = format_ui_names(items)

    # guard 1: bootstrap ANTES do planner (senão a decisão do 1B é descartada
    # e a latência, paga à toa).
    boot = _app_bootstrap(instruction, step, (title or "").lower())
    if boot is not None:
        return Decision(action=boot, source="planner", confidence=1.0,
                        reason="bootstrap janela do app"), t

    last_error = ctx.get("last_error", "")
    try:
        dec, pms = planner.next_action(
            goal=instruction, window=title, ui_names=names,
            history=ctx.get("hist_labels", []), last_error=last_error)
    except Exception as e:
        raise RuntimeError(f"planner falhou: {e}")
    t["planner_ms"] = round(pms, 1)
    t["planner_calls"] = 1
    t["planner_decision"] = dec.model_dump()
    ctx["last_error"] = ""

    # guard 2: anti-janela-errada — sem foco no alvo, planner deve focar/abrir;
    # se insistir em agir, devolve como last_error em vez de executar.
    if _has_any(instruction, CALC_WORDS) and "calcul" not in title.lower() \
            and dec.type in ("type_text", "uia_click", "visual_action",
                             "press_key", "hotkey"):
        raise RuntimeError(f"janela ativa é {title!r}, não a calculadora; "
                           "use focus_window ou open_app primeiro.")

    if ctx.get("no_vision") and dec.type == "visual_action":
        raise RuntimeError("visão desabilitada (no_vision); use uia_click, "
                           "type_text ou teclado.")

    # guard 4: `done` só com evidência — ao menos uma ação real executada.
    if dec.type == "done" and not done_allowed(ctx.get("hist_labels", [])):
        raise RuntimeError("'done' recusado: nenhuma ação foi executada ainda; "
                           "execute o objetivo antes de concluir.")

    try:
        native = _planner_to_action(dec)
    except ValueError as e:  # whitelist de app / URL inválida
        raise RuntimeError(str(e))
    if native is not None:
        return Decision(action=native, source="planner", confidence=0.9,
                        reason=f"planner {_short(dec)}"), t

    if dec.type == "uia_click":
        hit = _resolve_uia(items, dec.target or "", wrect, state_title=title)
        if hit is not None:
            return Decision(action=hit, source="uia", confidence=0.9,
                            reason=f'uia_click("{dec.target}")'), t
        if ctx.get("no_vision"):
            raise RuntimeError(f"uia_click: {dec.target!r} não está na "
                               "accessibility tree e a visão está desabilitada.")
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
        va, vms = vocaela.act_sync(img, dec.instruction or "",
                                   history=ctx.get("hist_labels", []))
    except Exception as e:
        raise RuntimeError(f"vocaela falhou: {e}")
    t["vision_ms"] = round(vms, 1)
    t["vision_calls"] = 1
    t["visual"] = va.model_dump()
    if va.dropped:
        t["visual_dropped"] = va.dropped
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
_NO_OP_PREFIXES = ("wait(", "answer(")


def done_allowed(hist_labels: list[str]) -> bool:
    """`done` exige ao menos uma ação executada que não seja wait/answer."""
    return any(not h.startswith(_NO_OP_PREFIXES) for h in hist_labels)


def observe(action: Action, before_title: str, after_title: str,
            value: str = "") -> str:
    """Resultado da ação em texto curto p/ o planner (puro, testável).

    Só fatos observados: janela antes/depois, e p/ `type` se o texto
    apareceu no campo focado. Nunca conclui "sucesso" do objetivo.
    """
    parts = []
    if after_title and after_title != before_title:
        parts.append(f"window {before_title or '?'!r} -> {after_title!r}")
    else:
        parts.append(f"window {after_title or '?'!r}")
    if action.type == "type" and action.text:
        if value and action.text.strip()[:40] in value:
            parts.append("text visible in focused field")
        elif value:
            parts.append(f"focused field now: {value[:60]!r}")
        else:
            parts.append("focused field unreadable")
    elif action.type in ("open", "focus") and after_title == before_title:
        parts.append("no window change yet")
    return "; ".join(parts)


def verify(action: Action, instruction: str, cfg: dict,
           before_title: str = "") -> tuple[bool, str]:
    """Espera curta + observação (título, campo focado). Não decide nada."""
    time.sleep(max(0, int(cfg.get("verify_wait_ms", 500))) / 1000.0)
    if safety.stop_requested():
        return False, "aborted"
    _items, title, _ = active_window_snapshot()
    value = focused_value() if action.type == "type" else ""
    return bool(title), observe(action, before_title, title, value)


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


def _build_models(cfg: dict) -> tuple[MiniCPMPlanner, VocaelaAdapter]:
    pc = cfg.get("planner", {})
    vc = cfg.get("vision", {})
    planner = MiniCPMPlanner(base_url=pc.get("base_url", "http://127.0.0.1:8091/v1"),
                             model=pc.get("model", "MiniCPM5-1B"),
                             temperature=float(pc.get("temperature", 0.1)),
                             timeout_s=float(pc.get("timeout_s", 90)))
    vocaela = VocaelaAdapter(
        base_url=vc.get("base_url", "http://127.0.0.1:8082/v1"),
        model=vc.get("model", "Vocaela-2-500M-1024R2"),
        timeout_s=float(vc.get("timeout_s", 180)),
        max_long_edge=int(cfg.get("screenshot_max_width", 1024)))
    return planner, vocaela


def _ensure_local_servers(cfg: dict) -> dict:
    """Sobe os 2 llama-server se os endpoints são desta máquina e estão caídos.

    1ª execução baixa runtime+GGUFs em models/ (gitignored); nas seguintes,
    só sobe/reusa. Config `runtime.auto_start: false` desliga. URLs remotas
    (Sandbox → HOST_IP) são responsabilidade do host: nada é baixado aqui.
    Retorna procs {"planner": Popen|None, "vision": Popen|None}.
    """
    rt = cfg.get("runtime", {})
    if not bool(rt.get("auto_start", True)):
        return {}
    urls = (cfg.get("planner", {}).get("base_url", "http://127.0.0.1:8091/v1"),
            cfg.get("vision", {}).get("base_url", "http://127.0.0.1:8082/v1"))
    if not server.needs_local_serve(urls):
        return {}
    try:
        return server.ensure_servers(urls, cfg)
    except Exception as e:
        raise RuntimeError(f"runtime local dos modelos falhou: {e}")


# --- run ----------------------------------------------------------------------
def run(instruction: str, cfg: dict) -> dict:
    max_steps = int(cfg.get("max_steps", 30))
    print(f"Task: {instruction}")
    print(f"Stop: {safety.HOTKEY} | Ctrl+C no terminal.")
    if LOG.exists():
        LOG.unlink()

    # --- sobe os dois modelos: OBRIGATÓRIOS (decisão 100% por modelos) ---
    # Runtime próprio: se os endpoints são locais e estão caídos, sobe
    # llama-server (baixa GGUFs na 1ª vez). URLs remotas: responsabilidade
    # de quem as expõe (ex.: host p/ o Sandbox).
    procs: dict = {}
    try:
        procs = _ensure_local_servers(cfg)
    except RuntimeError as e:
        print(f"RUNTIME DOS MODELOS: {e}")
        print("Sem fallback programático: os modelos decidem. Corrija e rode de novo.")
        _log({"event": "no_model", "planner": str(e)[:200]})
        return {"test": instruction, "result": "no_model", "steps": 0,
                "retries": 0, "planner_calls": 0, "vocaela_calls": 0}

    planner, vocaela = _build_models(cfg)
    st = planner.check()
    if not st.get("ok"):
        print(f"Planner MiniCPM5-1B OFFLINE: {st.get('error')}")
        print(f"Suba o planner ({planner.base_url}) ou rode `uv run python -m server`. "
              "Sem fallback programático: os modelos decidem.")
        _log({"event": "no_model", "planner": str(st.get("error"))[:200]})
        server.stop_servers(procs)
        return {"test": instruction, "result": "no_model", "steps": 0,
                "retries": 0, "planner_calls": 0, "vocaela_calls": 0}
    no_vision = bool(cfg.get("no_vision", False))
    vs = vocaela.check()
    if not vs.get("ok") and not no_vision:
        print(f"Vocaela OFFLINE ({vs.get('error')}); visual_action vai falhar — "
              f"suba o runtime da visão ({vocaela.base_url}) ou `uv run python -m server`.")
    print(f"Planner: MiniCPM ({planner.base_url} modelos={st.get('models')})")
    print(f"Visão: Vocaela ({vocaela.base_url} "
          f"{'ok' if vs.get('ok') else 'OFFLINE: ' + str(vs.get('error'))[:80]})")

    # safety + overlay só DEPOIS dos checks: nada de borda "controlado" órfã.
    safety.start(cfg.get("stop_hotkey"))
    try:
        import overlay as _ov

        ov_on = _ov.start()
    except Exception:
        ov_on = False
    print(f"Overlay de controle: {'ON (borda azul)' if ov_on else 'OFF (tkinter indisponível)'}")

    ctx: dict = {"no_vision": no_vision, "hist_labels": [], "last_error": ""}
    metrics = {"planner_ms": 0.0, "uia_ms": 0.0, "screenshot_ms": 0.0,
               "vision_ms": 0.0, "execution_ms": 0.0, "step_ms": 0.0,
               "vision_calls": 0, "planner_calls": 0, "steps": 0, "retries": 0}
    history: list[str] = []
    line = 0
    retries = 0  # consecutivos; NÃO consomem max_steps
    step = 0
    total0 = time.perf_counter()
    result = "stopped"

    def emit(layer: str, msg: str, ms) -> None:
        nonlocal line
        line += 1
        print(f"[{line}] {layer:<7} {msg} {ms}" if ms != "" else f"[{line}] {layer:<7} {msg}")

    def fail_step(kind: str, err: str) -> bool:
        """Registra erro recuperável; True = continuar (retry), False = parar."""
        nonlocal retries
        retries += 1
        metrics["retries"] += 1
        ctx["last_error"] = err[:300]
        if retries > MAX_RETRIES:
            print(f"PARADO step {step}: {kind} falhou {retries}x: {err}")
            _log({"step": step, "event": "stuck", "kind": kind, "error": err[:300]})
            return False
        print(f"[retry {retries}/{MAX_RETRIES}] step {step}: {err}")
        _log({"step": step, "event": "retry", "kind": kind, "error": err[:300]})
        time.sleep(0.5)
        return True

    try:
        while step < max_steps:
            if safety.stop_requested():
                _log({"step": step, "event": "aborted"})
                result = "aborted"
                break
            s0 = time.perf_counter()

            try:
                dec, tm = decide(instruction, step, ctx, cfg, planner, vocaela)
            except RuntimeError as e:
                if fail_step("decisao", str(e)):
                    continue
                result = "stuck"
                break

            metrics["planner_ms"] += tm.get("planner_ms", 0)
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
                    vinstr = tm.get("planner_decision", {}).get("instruction", "")
                    emit("PLANNER", f"visual: {vinstr}",
                         f'{tm.get("planner_ms", 0):.0f}ms')
                    if tm.get("screenshot_ms"):
                        emit("SHOT", "active-window capture",
                             f'{tm.get("screenshot_ms", 0):.0f}ms')
                    dropped = tm.get("visual_dropped")
                    extra = f" (+{dropped} descartadas)" if dropped else ""
                    emit("VISION", f'{va.get("type")}({va.get("x")}, {va.get("y")}){extra}',
                         f'{tm.get("vision_ms", 0):.0f}ms')
                else:  # uia
                    emit("PLANNER", f'uia: {dec.reason}',
                         f'{tm.get("planner_ms", 0):.0f}ms')

            # guard 3: anti-repetição — mesma ação 3x vira last_error p/ o
            # planner (ele decide outra coisa); se persistir -> stop.
            k = _key(dec.action)
            history.append(k)
            if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
                if not ctx.get("loop_warned"):
                    ctx["loop_warned"] = True
                    history.clear()
                    if fail_step("repeticao", f"você repetiu {dec.action.type} 3 vezes "
                                              "sem avançar; escolha uma ação DIFERENTE."):
                        continue
                    result = "stuck"
                    break
                print("loop persistente -> stop.")
                _log({"step": step, "event": "loop"})
                result = "loop"
                break

            e0 = time.perf_counter()
            try:
                desc = execute(dec.action)
            except ValueError as e:
                # coords fora da tela, app fora da whitelist...: o planner
                # recebe o motivo e tenta outra coisa; nunca clica no escuro.
                _log({"step": step, "event": "refused", "error": str(e)})
                if fail_step("acao recusada", str(e)):
                    continue
                result = "stuck"
                break
            retries = 0
            exec_ms = (time.perf_counter() - e0) * 1000
            metrics["execution_ms"] += exec_ms
            emit("EXEC", desc, f"{exec_ms:.0f}ms")

            label = desc
            if src == "vocaela" and tm.get("visual"):
                va = tm["visual"]
                label = (f'visual "{tm.get("planner_decision", {}).get("instruction", "")}"'
                         f" -> {va.get('type')}")
            if dec.action.type == "answer":
                # observação textual do Vocaela: devolve ao planner, sem input
                ctx["last_error"] = f"visão respondeu: {dec.action.text}"[:300]

            if dec.action.type == "done":
                ctx["hist_labels"].append(label)
                result = "done"
                break

            ok, vnote = verify(dec.action, instruction, cfg,
                               before_title=tm.get("uia_title", ""))
            # o planner vê ação + resultado observado no histórico
            ctx["hist_labels"].append(f"{label} => {vnote}")
            emit("VERIFY", vnote, "")
            metrics["steps"] += 1
            _log({"step": step, "source": dec.source, "confidence": dec.confidence,
                  "reason": dec.reason, "did": desc, "action": dec.action.model_dump(),
                  "verify": vnote, "timings": tm,
                  "cpu": psutil.cpu_percent(interval=None),
                  "mem": round(psutil.virtual_memory().percent, 1)})
            metrics["step_ms"] += (time.perf_counter() - s0) * 1000
            step += 1
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
        server.stop_servers(procs)  # só encerra os que NÓS subimos

    total_ms = time.perf_counter() - total0
    print(f"\n{result.upper()}")
    print(f"Total: {total_ms:.1f}s")
    pcalls = metrics["planner_calls"]
    vcalls = metrics["vision_calls"]
    summary = {"test": instruction, "result": result,
               "steps": metrics["steps"], "retries": metrics["retries"],
               "planner_calls": pcalls, "vocaela_calls": vcalls,
               "total_s": round(total_ms, 1),
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
