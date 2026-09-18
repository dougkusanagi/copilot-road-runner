"""CLI mínima: python main.py \"instrução\" [--self-test]"""
from __future__ import annotations

import argparse
import json
import time

import psutil


def main() -> None:
    ap = argparse.ArgumentParser(description="Computer Use local MVP")
    ap.add_argument("instruction", nargs="?", default="", help="instrução do usuário")
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--self-test", action="store_true", help="só testa screenshot + métricas, sem clicar")
    ap.add_argument("--no-vlm", action="store_true", help="desativa fallback VLM (só determinístico/UIA)")
    ap.add_argument("--lmstudio-url", default="http://localhost:1234/v1")
    args = ap.parse_args()

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
            "note": "pressione ESC p/ testar abort; dry-run sem cliques",
        }, indent=2))
        return

    # Loop completo (F4). Se ainda não implementado, avisa.
    try:
        from loop import run
    except ImportError as e:
        print(f"loop ainda não implementado ({e}). Rode com --self-test.")
        raise SystemExit(2)
    run(args.instruction, max_steps=args.max_steps, use_vlm=not args.no_vlm,
        lmstudio_url=args.lmstudio_url)


if __name__ == "__main__":
    main()
