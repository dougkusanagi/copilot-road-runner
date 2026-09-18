"""Loop observe → decide → act → repeat (MVP).

Estratégia de decisão (barata primeiro):
  1. bootstrap determinístico do browser (steps 0-3, se instrução pedir browser/busca)
  2. UIA pick por palavras-chave (scorer >= 0.6)
  3. VLM fallback (LM Studio) — pulado com --no-vlm ou se offline
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
from scorer import THRESHOLD_VLM, pick
from uia import snapshot

LOG = Path("run.jsonl")

BROWSER_CMDS = ["msedge", "chrome", "brave"]
BROWSER_WORDS = ["browser", "navegador", "edge", "chrome", "brave", "busque", "buscar",
                 "pesquise", "search", "google"]


def _log(obj: dict) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _wants_browser(instruction: str) -> bool:
    ins = instruction.lower()
    return any(w in ins for w in BROWSER_WORDS)


def _extract_search_query(instruction: str) -> str:
    """Extrai 'X' de padrões como: busque X / pesquise X / search X / buscar 'X'."""
    m = re.search(r"(?:busque|buscar|pesquise|pesquisar|search|procure)\s+[\"']?(.+?)[\"']?$",
                  instruction, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _browser_bootstrap(step: int, instruction: str) -> Action | None:
    """Sequência fixa e rápida: abrir → focar barra (ctrl+l) → digitar busca → enter."""
    if not _wants_browser(instruction):
        return None
    query = _extract_search_query(instruction)
    if step == 0:
        # tenta Edge, cai p/ chrome/brave se preciso (open é fire-and-forget)
        return Action(type="open", target="msedge")
    if step == 1:
        return Action(type="hotkey", key="ctrl+l")
    if step == 2:
        text = query or instruction
        # busca direta no Google se não for URL
        if not text.startswith("http"):
            text = f"https://www.google.com/search?q={text.replace(' ', '+')}"
        return Action(type="type", text=text)
    if step == 3:
        return Action(type="hotkey", key="enter")
    return None


def _uia_summary(elements) -> str:
    lines = []
    for e in elements[:80]:
        lines.append(f"[{e.control_type}] {e.name!r} aid={e.automation_id!r} "
                     f"rect={e.rect} d={e.depth}")
    return "\n".join(lines)


def decide(instruction: str, step: int, use_vlm: bool, lmstudio_url: str) -> Decision:
    # 1. bootstrap browser (determinístico, confiança alta)
    boot = _browser_bootstrap(step, instruction)
    if boot is not None:
        return Decision(action=boot, source="deterministic", confidence=0.9,
                        reason="browser bootstrap")

    # 2. UIA: observa e tenta match por palavras relevantes
    elements = snapshot()
    words = [w for w in re.findall(r"\w+", instruction.lower()) if len(w) > 3][:6]
    best, best_s = None, 0.0
    for w in words:
        el, s = pick(w, elements)
        if s > best_s:
            best, best_s = el, s
    if best is not None and best_s >= THRESHOLD_VLM:
        from tools import click_element

        return Decision(action=click_element(best), source="uia",
                        confidence=best_s, reason=f"uia match {best.name!r}")

    # 3. VLM fallback
    if use_vlm:
        from vlm import check_lmstudio, ground_action

        status = check_lmstudio(lmstudio_url)
        if not status.get("ok"):
            raise RuntimeError(
                f"sem match UIA (melhor={best_s:.2f}) e LM Studio offline: "
                f"{status.get('error')}. Suba um modelo vision no LM Studio ou rode com --no-vlm.")
        from obs import LAST_PNG

        b64, vlm_size = downscale_for_vlm(LAST_PNG)
        _, real = take_screenshot()  # garante last.png atual; barato (~250ms)
        # re-deriva real_size do screenshot atual
        act = ground_action(instruction, b64, _uia_summary(elements),
                            base_url=lmstudio_url, vlm_size=vlm_size, real_size=real)
        return Decision(action=act, source="vlm", confidence=0.5, reason="vlm fallback")

    raise RuntimeError(f"sem match UIA (melhor={best_s:.2f}) e --no-vlm ativo. "
                       "Refine a instrução ou ative o LM Studio.")


def run(instruction: str, max_steps: int = 15, use_vlm: bool = True,
        lmstudio_url: str = "http://localhost:1234/v1") -> None:
    print(f"instruction: {instruction!r} max_steps={max_steps} vlm={use_vlm}")
    print("Pressione ESC para abortar. Mouse no canto superior-esquerdo também aborta.")
    safety.start()
    if LOG.exists():
        LOG.unlink()

    for step in range(max_steps):
        if safety.stop_requested():
            print("abortado via ESC.");
            _log({"step": step, "event": "aborted"});
            break
        t0 = time.perf_counter()
        path, real_size = take_screenshot()
        try:
            dec = decide(instruction, step, use_vlm, lmstudio_url)
        except RuntimeError as e:
            print(f"[step {step}] PARADO: {e}");
            _log({"step": step, "event": "stuck", "error": str(e)});
            break
        desc = execute(dec.action)
        dt = (time.perf_counter() - t0) * 1000
        entry = {"step": step, "source": dec.source, "confidence": dec.confidence,
                 "reason": dec.reason, "did": desc,
                 "action": dec.action.model_dump(), "ms": round(dt, 1),
                 "cpu": psutil.cpu_percent(interval=None),
                 "mem": round(psutil.virtual_memory().percent, 1)}
        _log(entry)
        print(f"[step {step}] {dec.source}:{desc} ({dt:.0f}ms) — {dec.reason}")
        if dec.action.type == "done":
            print("tarefa concluída (VLM retornou done).");
            break
        time.sleep(0.5)
    else:
        print("max_steps atingido.")
    safety.stop()
    print(f"log em {LOG}")
