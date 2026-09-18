"""Trava de segurança MVP: hotkey ESC aborta o loop.

Usa `keyboard` se disponível; se falhar (ex: sem permissão),
faz fallback silencioso para checagem via pyautogui FAILSAFE
(o próprio pyautogui já aborta ao encostar no canto).
"""
from __future__ import annotations

import threading

_stop = threading.Event()
_keyboard_ok = False
_keyboard_error: str | None = None


def _poll_esc() -> None:
    global _keyboard_ok, _keyboard_error
    try:
        import keyboard  # type: ignore

        _keyboard_ok = True
        while not _stop.is_set():
            try:
                if keyboard.is_pressed("esc"):
                    _stop.set()
                    break
            except Exception:
                pass
            _stop.wait(0.1)
    except Exception as e:  # keyboard indisponível: loop segue só com FAILSAFE
        _keyboard_error = str(e)
        _keyboard_ok = False


_thread: threading.Thread | None = None


def start() -> None:
    global _thread
    _stop.clear()
    _thread = threading.Thread(target=_poll_esc, daemon=True)
    _thread.start()


def stop_requested() -> bool:
    return _stop.is_set()


def status() -> dict:
    return {"keyboard_ok": _keyboard_ok, "keyboard_error": _keyboard_error}


def stop() -> None:
    _stop.set()
