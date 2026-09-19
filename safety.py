"""Trava de segurança MVP: Ctrl+Alt+Esc cancela o loop (Ctrl+C também funciona).

Usa `keyboard` se disponível; se falhar (ex: sem permissão),
o failsafe do pyautogui (mouse no canto superior-esquerdo) continua valendo.

ESC puro NÃO aborta: o planner pode emitir `press_key: esc` (fechar diálogo)
e o usuário pode usar ESC no Sandbox; só a combinação dedicada para o loop.
"""
from __future__ import annotations

import threading

_stop = threading.Event()
_keyboard_ok = False
_keyboard_error: str | None = None
DEFAULT_HOTKEY = "ctrl+alt+esc"
HOTKEY = DEFAULT_HOTKEY


def _watch() -> None:
    global _keyboard_ok, _keyboard_error
    try:
        import keyboard  # type: ignore

        _keyboard_ok = True
        try:
            keyboard.add_hotkey(HOTKEY, _stop.set)
        except Exception:
            pass
        while not _stop.is_set():
            try:
                if keyboard.is_pressed(HOTKEY):
                    _stop.set()
                    break
            except Exception:
                pass
            _stop.wait(0.1)
    except Exception as e:  # keyboard indisponível: loop segue só com FAILSAFE
        _keyboard_error = str(e)
        _keyboard_ok = False


_thread: threading.Thread | None = None


def normalize_hotkey(hotkey: str | None) -> str:
    return ((hotkey or "").strip().lower()) or DEFAULT_HOTKEY


def start(hotkey: str | None = None) -> None:
    """Sobe o watcher. `hotkey` vem de cfg["stop_hotkey"] (default ctrl+alt+esc)."""
    global _thread, HOTKEY
    HOTKEY = normalize_hotkey(hotkey)
    _stop.clear()
    _thread = threading.Thread(target=_watch, daemon=True)
    _thread.start()


def stop_requested() -> bool:
    return _stop.is_set()


def status() -> dict:
    return {"keyboard_ok": _keyboard_ok, "keyboard_error": _keyboard_error,
            "hotkey": HOTKEY}


def stop() -> None:
    _stop.set()
