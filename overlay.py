"""Overlay de controle: borda azul + aviso, estilo Quick Assist/Teams.

Fullscreen por monitor, click-through (WS_EX_TRANSPARENT), sempre no topo.
Falha silenciosa (retorna False) se tkinter indisponível — nunca bloqueia o MVP.
"""
from __future__ import annotations

_BLUE = "#0078D4"
_BW = 7
_TEXT = "Este computador está sendo controlado pelo agente   |   Ctrl+Alt+Esc para parar"

_started = False
_proc = None


def _monitors() -> list[tuple[int, int, int, int]]:
    try:
        import mss

        with mss.mss() as sct:
            return [(m["left"], m["top"], m["width"], m["height"])
                    for m in sct.monitors[1:]]
    except Exception:
        return [(0, 0, 1920, 1080)]


def show() -> None:
    """Bloqueante: mostra o overlay na thread principal (rode em processo próprio)."""
    import tkinter as tk
    import ctypes

    wins = []
    for i, (x, y, w, h) in enumerate(_monitors()):
        win = tk.Tk() if i == 0 else tk.Toplevel()
        if i == 0:
            root = win
        win.overrideredirect(True)
        # geometria inicial (Tk não lida bem com offset negativo); o
        # posicionamento exato vem via SetWindowPos abaixo.
        win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        win.attributes("-topmost", True)
        win.configure(bg="black")
        try:
            win.attributes("-transparentcolor", "black")
        except Exception:
            pass
        try:  # click-through: cliques atravessam o overlay
            hwnd = win.winfo_id()
            u = ctypes.windll.user32
            ex = u.GetWindowLongW(hwnd, -20)
            u.SetWindowLongW(hwnd, -20, ex | 0x20 | 0x80000 | 0x08000000)
        except Exception:
            pass
        bar = {"bg": _BLUE, "bd": 0, "highlightthickness": 0}
        tk.Frame(win, **bar).place(x=0, y=0, relwidth=1, height=_BW)
        tk.Frame(win, **bar).place(x=0, rely=1.0, y=-_BW, relwidth=1, height=_BW)
        tk.Frame(win, **bar).place(x=0, y=0, width=_BW, relheight=1)
        tk.Frame(win, **bar).place(relx=1.0, x=-_BW, y=0, width=_BW, relheight=1)
        banner = tk.Label(win, text=_TEXT, bg=_BLUE, fg="white",
                          font=("Segoe UI", 11, "bold"), padx=14, pady=6)
        banner.place(relx=0.5, y=_BW + 2, anchor="n")
        wins.append(win)
    try:  # posicionamento exato por monitor (cobre offsets negativos)
        root.update_idletasks()
        u = ctypes.windll.user32
        for win, (x, y, w, h) in zip(wins, _monitors()):
            try:
                u.SetWindowPos(win.winfo_id(), -1, x, y, w, h, 0x0010 | 0x0040)
            except Exception:
                pass
    except Exception:
        pass
    root.mainloop()


def start() -> bool:
    """Sobe o overlay em processo próprio. Retorna False se indisponível."""
    global _started, _proc
    if _started and _proc is not None and _proc.poll() is None:
        return True
    try:
        import os
        import subprocess
        import sys

        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.devnull, "w") as dn:
            _proc = subprocess.Popen([sys.executable, os.path.join(here, "overlay.py")],
                                     stdout=dn, stderr=dn)
        import time

        time.sleep(1.0)
        if _proc.poll() is None:
            _started = True
            return True
        return False
    except Exception:
        return False


def stop() -> None:
    global _started, _proc
    try:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=3)
            except Exception:
                _proc.kill()
    except Exception:
        pass
    _proc = None
    _started = False


if __name__ == "__main__":
    show()
