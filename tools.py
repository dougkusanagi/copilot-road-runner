"""Ferramentas determinísticas. Registry simples de funções, sem framework."""
from __future__ import annotations

import time

# Whitelist: o alvo vem do PLANNER (que lê texto de tela) e por isso nunca
# passa por shell. Fora daqui = erro honesto (vira last_error p/ o modelo).
# Não há "teleporte p/ URL": navegar é pela UI do navegador (ctrl+l, digitar,
# enter, cliques), como um humano — por isso open_url foi removido.
APP_COMMANDS = {
    "msedge": "msedge", "edge": "msedge", "microsoft edge": "msedge",
    "chrome": "chrome", "brave": "brave",
    "notepad": "notepad", "notepad.exe": "notepad", "bloco de notas": "notepad",
    "calc": "calc", "calc.exe": "calc", "calculator": "calc", "calculadora": "calc",
}


_FOCUS_HINTS = {
    "msedge": "edge||msedge", "edge": "edge||msedge",
    "microsoft edge": "edge||msedge",
    "chrome": "chrome", "brave": "brave",
    "notepad": "bloco de notas||notepad", "notepad.exe": "bloco de notas||notepad",
    "bloco de notas": "bloco de notas||notepad",
    "calc": "calculadora||calculator", "calc.exe": "calculadora||calculator",
    "calculator": "calculadora||calculator", "calculadora": "calculadora||calculator",
}


def open_app(target: str) -> str:
    """Abre app da whitelist via ShellExecute (App Paths resolve msedge etc.).

    Equivale a clicar no ícone/Menu Iniciar: a partir daqui tudo é UI
    (teclado/mouse/tela). Nunca usa shell=True: sem injeção via `&`, `"` ou `%`.

    Lançar ≠ estar em primeiro plano (cold start lento, foreground-lock do
    Windows): por isso aguarda a janela (polling generoso — Chrome com
    perfis pode levar >10s) e RELATA o resultado.
    """
    key = target.strip().lower()
    exe = APP_COMMANDS.get(key)
    if exe is None:
        raise ValueError(f"app fora da whitelist: {target!r}; "
                         f"use um de {sorted(set(APP_COMMANDS.values()))}")
    _launch(exe)
    time.sleep(1.2)
    if focus_window(_FOCUS_HINTS.get(key, key), timeout=15.0):
        return f"opened {exe} (janela ativa)"
    return f"opened {exe} (janela ainda não em primeiro plano)"


def _launch(exe: str) -> None:
    """ShellExecute (resolve App Paths: msedge/chrome) com fallback Popen em lista."""
    import os
    import subprocess

    try:
        os.startfile(exe)
    except OSError:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


