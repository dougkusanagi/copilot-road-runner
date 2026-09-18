"""CLI: python main.py  →  > Abra o Notepad e escreva Hello World"""
from __future__ import annotations

import argparse
import json
import time

import psutil

import config as cfgmod


def locate_only(target: str, cfg: dict) -> None:
    """Dry-run do grounding: screenshot → locate → imprime coords, sem clicar."""
    from obs import downscale_for_vlm, take_screenshot
    from vlm import LMStudioVisionModel

    path, real = take_screenshot()
    b64, _ = downscale_for_vlm(path, max_width=int(cfg.get("screenshot_max_width", 1280)))
    vm = LMStudioVisionModel(base_url=cfg["base_url"], model=cfg.get("vision_model", "MAI-UI-2B"))
    res = vm.locate_sync(b64, target)
    rw, rh = real
    print(json.dumps({"target": target, "x": res.x, "y": res.y,
                      "confidence": res.confidence,
                      "pixels": [int(res.x * rw), int(res.y * rh)],
                      "screen": list(real)}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Computer Use local MVP")
    ap.add_argument("instruction", nargs="?", default="", help="instrução do usuário")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--self-test", action="store_true", help="só testa screenshot + métricas, sem clicar")
    ap.add_argument("--no-vlm", action="store_true", help="desativa fallback VLM (só determinístico/UIA+scorer)")
    ap.add_argument("--lmstudio-url", default=None, help="override de base_url")
    ap.add_argument("--locate", default="", help='dry-run grounding: --locate "botão Continue"')
    args = ap.parse_args()

    cfg = cfgmod.load(args.config)
    if args.max_steps is not None:
        cfg["max_steps"] = args.max_steps
    if args.no_vlm:
        cfg["no_vlm"] = True
    if args.lmstudio_url:
        cfg["base_url"] = args.lmstudio_url

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
