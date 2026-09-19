"""Config do MVP de 2 modelos: MiniCPM5-1B (planner) + Vocaela-2-500M (visão).

Dois servidores locais (podem ser llama.cpp, LM Studio ou outro runtime):
  planner: http://127.0.0.1:8091/v1   (MiniCPM5-1B, texto, SEM screenshots)
  vision:  http://127.0.0.1:8082/v1   (Vocaela-2-500M-1024R2, screenshot+instrução)

Migra config.json legado (base_url/vision_model) automaticamente.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS: dict = {
    "planner": {
        "provider": "llama.cpp",
        "base_url": "http://127.0.0.1:8091/v1",
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
    # --- runtime próprio dos modelos (server.py: baixa e sobe llama-server) ---
    "runtime": {
        "auto_start": True,  # endpoints locais caídos -> baixa GGUFs e sobe
        "host": "127.0.0.1",  # bind dos llama-server (0.0.0.0 p/ expor ao Sandbox)
        "ngl": 0,  # 0 = CPU; >0 offload p/ GPU (quem tem VRAM)
        "threads": 0,  # 0 = metade dos núcleos (server.DEFAULT_THREADS)
        "ctx": 4096,
        # Carga do GGUF com Defender/HDD leva minutos (polling até o deadline)
        "startup_timeout_s": 600,
    },
    # --- tray + janela Spotlight (main.py --ui; extra `ui`) ---
    "ui": {
        "hotkey": "ctrl+alt+space",  # mostra/esconde a janela
        "width": 720,
        "auto_hide": True,  # esconde a janela enquanto o agente age
    },
    # --- ditado ao vivo (faster-whisper int8 em CPU) ---
    "stt": {
        "engine": "faster-whisper",
        "model": "base",  # tiny|base|small (base ~74MB int8)
        "compute_type": "int8",
        "language": "pt",
        "partial_every_ms": 1000,  # retranscreve o buffer p/ mostrar parcial
        "silence_ms": 1500,  # silêncio contínuo -> transcrição final
        "silence_rms": 0.01,  # limiar de energia p/ "silêncio"
        "max_utterance_s": 30,
        "auto_send": True,  # final por silêncio envia sozinho
    },
}


def _migrate_legacy(cfg: dict) -> dict:
    """Aceita config.json antigo {base_url, vision_model, ...} e mapeia p/ novo."""
    legacy_url = cfg.pop("base_url", None)
    legacy_model = cfg.pop("vision_model", None)  # MAI-UI: aposentado do fluxo
    if legacy_url:
        for sec in ("planner", "vision"):
            cur = cfg.get(sec, {}).get("base_url", "")
            if sec not in cfg or cur in ("", DEFAULTS[sec]["base_url"]):
                cfg.setdefault(sec, {}).update(
                    {**DEFAULTS[sec], **cfg.get(sec, {}), "base_url": legacy_url})
        print(f"config legado migrado: base_url {legacy_url} aplicado a planner+vision; "
              f"ajuste config.json p/ 8091/8082.")
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
