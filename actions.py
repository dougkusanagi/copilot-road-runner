"""Ações de mouse/teclado via pyautogui. Sem abstração enterprise."""
from __future__ import annotations

import time

import pyautogui

pyautogui.FAILSAFE = True  # mouse no canto superior-esquerdo aborta
pyautogui.PAUSE = 0.15

from schemas import Action


def execute(action: Action) -> str:
    """Executa uma Action. Retorna descrição p/ log. Levanta exceção se falhar."""
    from tools import focus_window

    t = action.type
    if t == "click":
        assert action.x is not None and action.y is not None, "click precisa de x,y"
        pyautogui.moveTo(action.x, action.y, duration=0.15)
        pyautogui.click(x=action.x, y=action.y, clicks=action.clicks or 1)
        return f"click({action.x},{action.y})"
    if t == "double_click":
        assert action.x is not None and action.y is not None
        pyautogui.moveTo(action.x, action.y, duration=0.15)
        pyautogui.doubleClick(x=action.x, y=action.y)
        return f"double_click({action.x},{action.y})"
    if t == "right_click":
        assert action.x is not None and action.y is not None
        pyautogui.moveTo(action.x, action.y, duration=0.15)
        pyautogui.rightClick(x=action.x, y=action.y)
        return f"right_click({action.x},{action.y})"
    if t == "move":
        assert action.x is not None and action.y is not None
        pyautogui.moveTo(action.x, action.y, duration=0.15)
        return f"move({action.x},{action.y})"
    if t == "drag":
        assert action.x is not None and action.y is not None
        assert action.x2 is not None and action.y2 is not None, "drag precisa de x2,y2"
        pyautogui.moveTo(action.x, action.y, duration=0.15)
        pyautogui.dragTo(action.x2, action.y2, duration=0.4)
        return f"drag({action.x},{action.y}->{action.x2},{action.y2})"
    if t == "type":
        assert action.text, "type precisa de text"
        pyautogui.typewrite(action.text, interval=0.02)
        return f"type({len(action.text)} chars)"
    if t == "scroll":
        amount = int(action.text) if action.text and action.text.lstrip("-").isdigit() else -800
        pyautogui.scroll(amount)
        return f"scroll({amount})"
    if t == "hotkey":
        assert action.key, "hotkey precisa de key ex: 'enter', 'ctrl+l'"
        parts = [p.strip() for p in action.key.split("+")]
        pyautogui.hotkey(*parts)
        return f"hotkey({action.key})"
    if t == "open":
        import subprocess

        assert action.target, "open precisa de target"
        subprocess.Popen(action.target, shell=True)
        time.sleep(1.0)
        return f"open({action.target})"
    if t == "focus":
        assert action.target, "focus precisa de target (substring do título)"
        ok = focus_window(action.target)
        return f"focus({action.target})={'ok' if ok else 'miss'}"
    if t == "wait":
        time.sleep(max(0, action.ms) / 1000.0)
        return f"wait({action.ms}ms)"
    if t == "done":
        return "done"
    raise ValueError(f"action desconhecida: {t}")
