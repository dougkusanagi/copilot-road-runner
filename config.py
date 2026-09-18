"""Config do MVP de 2 modelos: MiniCPM5-1B (planner) + Vocaela-2-500M (visão).

Dois servidores locais (podem ser llama.cpp, LM Studio ou outro runtime):
  planner: http://127.0.0.1:8081/v1   (MiniCPM5-1B, texto, SEM screenshots)
  vision:  http://127.0.0.1:8082/v1   (Vocaela-2-500M-1024R2, screenshot+instrução)

Migra config.json legado (base_url/vision_model) automaticamente.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS: dict = {
    "planner": {
        "provider": "llama.cpp",
        "base_url": "http://127.0.0.1:8081/v1",
        "model": "MiniCPM5-1B",
        "temperature": 0.1,
        "timeout_s": 90,
    },
    "vision": {
        "provider": "llama.cpp",
        "base_url": "http://127.0.0.1:8082/v1",
        "model": "Vocaela-2-500M-1024R2",
        "timeout_s": 180,
    },
    "max_steps": 30,
    "screenshot_max_width": 1024,  # Vocaela-2-1024R2: treino em longest-edge 1024
    "verify_wait_ms": 500,
    "stop_hotkey": "ctrl+alt+esc",
}


def _migrate_legacy(cfg: dict) -> dict:
    """Aceita config.json antigo {base_url, vision_model, ...} e mapeia p/ novo."""
    legacy_url = cfg.pop("base_url", None)
    legacy_model = cfg.pop("vision_model", None)  # MAI-UI: aposentado do fluxo
    if legacy_url and ("planner" not in cfg or "vision" not in cfg):
        if "planner" not in cfg:
            cfg["planner"] = {**DEFAULTS["planner"], "base_url": legacy_url}
        if "vision" not in cfg:
            cfg["vision"] = {**DEFAULTS["vision"], "base_url": legacy_url}
        print(f"config legado migrado: base_url {legacy_url} aplicado a planner+vision; "
              f"ajuste config.json p/ 8081/8082.")
    if legacy_model and legacy_model != DEFAULTS["vision"]["model"]:
        print(f"modelo legado {legacy_model!r} fora do fluxo principal "
              f"(agora: Vocaela-2-500M-1024R2).")
    for junk in ("scorer_threshold",):
        cfg.pop(junk, None)  # scorer saiu do fluxo principal
    return cfg


def load(path: str | Path = "config.json") -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy simples
    p = Path(path)
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            # merge raso por seção p/ não perder defaults aninhados
            for k, v in raw.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k] = {**cfg[k], **v}
                else:
                    cfg[k] = v
            cfg = _migrate_legacy(cfg)
        except Exception as e:
            print(f"config.json inválido ({e}); usando defaults.")
    return cfg
