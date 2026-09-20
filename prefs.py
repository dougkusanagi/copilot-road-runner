"""Preferências entre sessões: separadas, versionadas, nunca observação.

§5.1: memória da tarefa dura UMA execução; preferências/procedimentos
(vale para "qual perfil do Chrome usar") vivem aqui, em `prefs.json`
(gitignored — pode conter nomes), com versão. O modelo lê via prompt;
o Python armazena/valida. Nunca tratado como estado atual da tela.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATH = ROOT / "prefs.json"
VERSION = 1


def load() -> dict:
    try:
        if PATH.is_file():
            raw = json.loads(PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {"version": VERSION}


def save(prefs: dict) -> None:
    prefs = dict(prefs or {})
    prefs["version"] = VERSION
    try:
        PATH.write_text(json.dumps(prefs, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except Exception:
        pass


def get(key: str, default: str = "") -> str:
    return str(load().get(key, default) or "")


def remember(key: str, value: str) -> None:
    """Guarda UMA preferência (ex.: browser_profile). Best-effort."""
    p = load()
    p[str(key)[:60]] = str(value or "")[:200]
    save(p)


def context_line() -> str:
    """Uma linha p/ o prompt (vazio = sem preferências). Puro, testável."""
    p = load()
    bits = [f"{k}={v}" for k, v in p.items()
            if k != "version" and str(v or "").strip()]
    if not bits:
        return ""
    return "Preferências lembradas (do HUMANO, valem mais que adivinhação): " \
        + "; ".join(bits[:8])
