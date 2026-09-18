"""Ferramentas determinísticas. Registry simples de funções, sem framework."""
from __future__ import annotations

import subprocess
import time

from schemas import Action, UIElement


APP_COMMANDS = {
    "msedge": 'cmd /c start "" msedge',
    "edge": 'cmd /c start "" msedge',
    "microsoft edge": 'cmd /c start "" msedge',
    "chrome": 'cmd /c start "" chrome',
    "brave": 'cmd /c start "" brave',
    "notepad": "notepad",
    "calc": "calc",
    "calculator": "calc",
}


def open_app(target: str) -> str:
    """Abre app. Resolve via `start` (App Paths) p/ navegadores; stdout some no log."""
    import os

    key = target.strip().lower()
    cmd = APP_COMMANDS.get(key, target)
    if key not in APP_COMMANDS and not key.endswith(".exe"):
        cmd = f'cmd /c start "" {target}'
    with open(os.devnull, "w") as dn:
        subprocess.Popen(cmd, shell=True, stdout=dn, stderr=dn)
    time.sleep(1.2)
    return f"opened {target}"


def open_url(url: str) -> Action:
    """Abre URL no navegador padrão (via open)."""
    return Action(type="open", target=f'cmd /c start "" "{url}"')


def focus_window(title_substr: str, timeout: float = 8.0) -> bool:
    """Traz janela p/ frente por substring do título. Aceita alternativas com '||'."""
    from pywinauto import Desktop

    alts = [a.strip().lower() for a in title_substr.split("||") if a.strip()]
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        try:
            desk = Desktop(backend="uia")
            matches = []
            for w in desk.windows(top_level_only=True, visible_only=True):
                try:
                    title = w.window_text() or ""
                    if any(a in title.lower() for a in alts):
                        matches.append((title, w))
                except Exception:
                    continue
            if matches:
                # prefere documento novo/untitled (não digita em doc do usuário)
                matches.sort(key=lambda tw: 0 if any(
                    k in tw[0].lower() for k in ("sem t", "untitled")) else 1)
                matches[0][1].set_focus()
                time.sleep(0.4)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def list_windows() -> list[str]:
    """Lista títulos das janelas visíveis (wrap de uia, evita import circular)."""
    from uia import find_window_titles

    return find_window_titles()


def click_element(el: UIElement) -> Action:
    x, y = el.center
    if x <= 0 and y <= 0:
        raise ValueError(f"elemento sem rect válido: {el.name!r}")
    return Action(type="click", x=x, y=y)


def type_text(text: str) -> Action:
    return Action(type="type", text=text)


def press(key: str) -> Action:
    """Uma tecla: 'enter', 'esc', 'tab', 'f5'. (alias de press_key)"""
    return Action(type="hotkey", key=key)


def press_key(key: str) -> Action:
    return Action(type="hotkey", key=key)


def hotkey(keys: str) -> Action:
    """Combo: 'ctrl+l', 'ctrl+alt+esc', 'alt+f4'."""
    return Action(type="hotkey", key=keys)


def wait(ms: int) -> Action:
    return Action(type="wait", ms=int(ms))


# Registry mínimo p/ planner futuro / depuração. Não é framework: só um dict.
TOOLS = {
    "open_app": open_app,
    "open_url": open_url,
    "focus_window": focus_window,
    "list_windows": list_windows,
    "type_text": type_text,
    "press_key": press_key,
    "hotkey": hotkey,
    "wait": wait,
}
