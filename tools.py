"""Ferramentas determinísticas. Registry simples de funções, sem framework."""
from __future__ import annotations

import time

from schemas import Action

# Whitelist: o alvo vem do PLANNER (que lê texto de tela) e por isso nunca
# passa por shell. Fora daqui = erro honesto (vira last_error p/ o modelo).
APP_COMMANDS = {
    "msedge": "msedge", "edge": "msedge", "microsoft edge": "msedge",
    "chrome": "chrome", "brave": "brave",
    "notepad": "notepad", "notepad.exe": "notepad", "bloco de notas": "notepad",
    "calc": "calc", "calc.exe": "calc", "calculator": "calc", "calculadora": "calc",
}
_URL_PREFIX = "url:"


def open_app(target: str) -> str:
    """Abre app da whitelist via ShellExecute (App Paths resolve msedge etc.).

    `url:https://...` (gerado por open_url) abre no navegador padrão.
    Nunca usa shell=True: sem injeção via `&`, `"` ou `%`.
    """
    import os

    if target.startswith(_URL_PREFIX):
        url = target[len(_URL_PREFIX):]
        os.startfile(url)
        time.sleep(1.2)
        return f"opened {url}"
    key = target.strip().lower()
    exe = APP_COMMANDS.get(key)
    if exe is None:
        raise ValueError(f"app fora da whitelist: {target!r}; "
                         f"use um de {sorted(set(APP_COMMANDS.values()))}")
    _launch(exe)
    time.sleep(1.2)
    return f"opened {exe}"


def _launch(exe: str) -> None:
    """ShellExecute (resolve App Paths: msedge/chrome) com fallback Popen em lista."""
    import os
    import subprocess

    try:
        os.startfile(exe)
    except OSError:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(url: str) -> Action:
    """Abre URL http(s) no navegador padrão. Recusa outros esquemas."""
    from urllib.parse import urlparse

    u = (url or "").strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc or any(c in u for c in ' "\n'):
        raise ValueError(f"URL inválida p/ open_url: {url!r} (só http/https)")
    return Action(type="open", target=f"{_URL_PREFIX}{u}")


def focus_window(title_substr: str, timeout: float = 3.0) -> bool:
    """Traz janela p/ frente por substring do título. Aceita alternativas com '||'."""
    from pywinauto import Desktop

    from overlay import is_overlay_title

    alts = [a.strip().lower() for a in title_substr.split("||") if a.strip()]
    t0 = time.perf_counter()
    desk = Desktop(backend="uia")
    while time.perf_counter() - t0 < timeout:
        try:
            matches = []
            for w in desk.windows(top_level_only=True, visible_only=True):
                try:
                    title = w.window_text() or ""
                    if is_overlay_title(title):
                        continue  # nunca focar a própria borda "controlado"
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
    # 2ª passada: janela pode estar minimizada (inclui ocultas + restore)
    try:
        for w in desk.windows(top_level_only=True, visible_only=False):
            try:
                title = w.window_text() or ""
                if is_overlay_title(title):
                    continue
                if not any(a in title.lower() for a in alts):
                    continue
                try:
                    w.restore()
                    time.sleep(0.4)
                except Exception:
                    pass
                w.set_focus()
                time.sleep(0.4)
                return True
            except Exception:
                continue
    except Exception:
        pass
    return False


