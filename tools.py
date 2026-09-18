"""Ferramentas determinísticas: abrir app, focar janela, clicar via UIA, digitar."""
from __future__ import annotations

import subprocess
import time

from schemas import Action, UIElement


def open_app(target: str) -> str:
    """Abre app via shell. Ex: 'msedge', 'notepad', 'calc'."""
    subprocess.Popen(target, shell=True)
    time.sleep(1.2)
    return f"opened {target}"


def focus_window(title_substr: str, timeout: float = 8.0) -> bool:
    """Traz janela p/ frente por substring do título. Retorna True se achou."""
    from pywinauto import Desktop

    t0 = time.perf_counter()
    title_substr = title_substr.lower()
    while time.perf_counter() - t0 < timeout:
        try:
            desk = Desktop(backend="uia")
            for w in desk.windows(top_level_only=True, visible_only=True):
                try:
                    title = w.window_text() or ""
                    if title_substr in title.lower():
                        w.set_focus()
                        time.sleep(0.4)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        time.sleep(0.5)
    return False


def click_element(el: UIElement) -> Action:
    x, y = el.center
    # rect inválido → não clicar no 0,0
    if x <= 0 and y <= 0:
        raise ValueError(f"elemento sem rect válido: {el.name!r}")
    return Action(type="click", x=x, y=y)


def type_text(text: str) -> Action:
    return Action(type="type", text=text)


def press(key: str) -> Action:
    """key ex: 'enter', 'ctrl+l', 'ctrl+t', 'alt+d'."""
    return Action(type="hotkey", key=key)
