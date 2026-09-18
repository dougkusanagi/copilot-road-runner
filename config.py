"""Config simples via config.json (com defaults). Sem framework."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS: dict = {
    "base_url": "http://127.0.0.1:1234/v1",
    "vision_model": "MAI-UI-2B",
    "max_steps": 20,
    "scorer_threshold": 0.8,
    "screenshot_max_width": 1280,
    "verify_wait_ms": 500,
    "stop_hotkey": "ctrl+alt+esc",
}


def load(path: str | Path = "config.json") -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"config.json inválido ({e}); usando defaults.")
    return cfg
