"""CLI: python main.py  →  > Abra o Notepad e escreva Hello World

Arquitetura de 2 modelos (config.json):
  planner MiniCPM5-1B  http://127.0.0.1:8091/v1  (texto, sem screenshots)
  visão   Vocaela-2    http://127.0.0.1:8082/v1  (screenshot → ação visual)
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import psutil

import config as cfgmod


def _dpi_aware() -> None:
    """GetWindowRect, mss e pyautogui na MESMA unidade (pixel físico) em DPI≠100%.
    Precisa rodar antes de qualquer janela/import de pywinauto/pyautogui."""
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_dpi_aware()

# Console Windows pode estar em cp1252: nunca quebrar por unicode (→, ç, ã...).
for _s in (sys.stdout, sys.stderr):
    try:
        if _s and _s.encoding and _s.encoding.lower() not in ("utf-8", "utf8"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def locate_only(target: str, cfg: dict) -> None:
    """Dry-run do grounding Vocaela: screenshot → act → imprime, sem clicar."""
    from obs import capture_for_vision
    from vocaela import VocaelaAdapter, visual_to_action

    vc = cfg.get("vision", {})
    img, origin, full = capture_for_vision(
        max_long_edge=int(cfg.get("screenshot_max_width", 1024)))
    va, vms = VocaelaAdapter(
        base_url=vc.get("base_url", "http://127.0.0.1:8082/v1"),
        model=vc.get("model", "Vocaela-2-500M-1024R2"),
        timeout_s=float(vc.get("timeout_s", 180)),
        max_long_edge=int(cfg.get("screenshot_max_width", 1024)),
    ).act_sync(img, target)
    act = visual_to_action(va, (img.size[0], img.size[1]), origin)
    print(json.dumps({"target": target, "visual": va.model_dump(),
                      "origin": list(origin), "crop": list(img.size),
                      "screen": list(full),
                      "physical": {"x": act.x, "y": act.y,
                                   "x2": act.x2, "y2": act.y2},
                      "vision_ms": round(vms, 1)}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Computer Use local (MiniCPM5-1B + Vocaela-2)")
    ap.add_argument("instruction", nargs="?", default="", help="instrução do usuário")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--self-test", action="store_true", help="só testa screenshot + métricas, sem clicar")
    ap.add_argument("--planner-url", default=None, help="override de planner.base_url")
    ap.add_argument("--vision-url", default=None, help="override de vision.base_url")
    ap.add_argument("--lmstudio-url", default=None,
                    help="override legado: aplica a planner+vision (deprecated)")
    ap.add_argument("--locate", default="", help='dry-run Vocaela: --locate "Click the address bar"')
    args = ap.parse_args()

    cfg = cfgmod.load(args.config)
    if args.max_steps is not None:
        cfg["max_steps"] = args.max_steps
    if args.planner_url:
        cfg["planner"]["base_url"] = args.planner_url
    if args.vision_url:
        cfg["vision"]["base_url"] = args.vision_url
    if args.lmstudio_url:
        cfg["planner"]["base_url"] = args.lmstudio_url
        cfg["vision"]["base_url"] = args.lmstudio_url

    if args.self_test:
        from obs import take_screenshot
        import safety

        safety.start()
        t0 = time.perf_counter()
        path, (w, h) = take_screenshot()
        dt = (time.perf_counter() - t0) * 1000
        print(json.dumps({
            "ok": True,
            "screenshot": path,
            "size": [w, h],
            "ms": round(dt, 1),
            "cpu_pct": psutil.cpu_percent(interval=0.2),
            "mem_pct": psutil.virtual_memory().percent,
            "safety": safety.status(),
            "config": cfg,
            "note": "Ctrl+Alt+Esc (ou ESC) aborta; dry-run sem cliques",
        }, indent=2))
        return

    if args.locate:
        locate_only(args.locate, cfg)
        return

    instruction = args.instruction.strip()
    if not instruction:
        try:
            instruction = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
    if not instruction:
        print("instrução vazia.")
        raise SystemExit(2)

    from loop import run
    summary = run(instruction, cfg)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
