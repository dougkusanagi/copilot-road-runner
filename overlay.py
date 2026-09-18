"""Overlay de controle: GLOW pulsante em volta de cada monitor + aviso.

Estilo apps de uso remoto (Quick Assist / Teams / indicador do Codex):
borda azul brilhante em camadas (halo escuro → núcleo claro) pulsando,
fullscreen por monitor, click-through (WS_EX_TRANSPARENT), sempre no topo.

Fixes vs versão anterior:
- winfo_id() do Tk devolve a janela INTERNA; os estilos WS_EX_* (click-through)
  precisam ir no HWND top-level (GetParent) — era a causa de o overlay bloquear
  interação/nao comportar-se como overlay em alguns monitores.
- Glow em 3 camadas por lado, com pulso via after() — em TODOS os monitores
  (EnumDisplayMonitors/mss cobre offsets negativos via SetWindowPos exato).

Falha silenciosa (retorna False) se tkinter indisponível — nunca bloqueia o MVP.
"""
from __future__ import annotations

import math

_BLUE = "#0078D4"
_GLOW = ("#0A4E8A", "#0078D4", "#66B2FF")  # halo externo → miolo → núcleo
_BASE = (10, 6, 3)   # larguras base (externa, meio, interna)
_AMP = 4              # amplitude do pulso (px) aplicada a todas as camadas
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


def _make_click_through(win) -> None:
    """WS_EX_* no HWND TOP-LEVEL (não no filho do Tk — bug do click-through)."""
    import ctypes
    from ctypes import wintypes

    try:
        u = ctypes.windll.user32
        u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        u.SetWindowLongW.restype = ctypes.c_long
        hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
        ex = u.GetWindowLongW(hwnd, -20)
        # TRANSPARENT (cliques atravessam) | LAYERED | TOOLWINDOW | NOACTIVATE
        u.SetWindowLongW(hwnd, -20, ex | 0x20 | 0x80000 | 0x80 | 0x08000000)
    except Exception:
        pass


def show() -> None:
    """Bloqueante: mostra o overlay na thread principal (rode em processo próprio)."""
    import ctypes
    import math
    import tkinter as tk

    mons = _monitors()
    wins: list[tuple] = []  # [(win, layers)] — layers = 3 anéis × 4 lados
    root = None
    for i, (x, y, w, h) in enumerate(mons):
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
        # glow: 3 camadas por lado (escura externa → clara interna). O pulso
        # anima as larguras via place_configure no loop after() abaixo.
        layers: list[dict[str, tk.Frame]] = []
        for layer in range(3):
            ring = {
                "top": tk.Frame(win, bd=0, highlightthickness=0),
                "bottom": tk.Frame(win, bd=0, highlightthickness=0),
                "left": tk.Frame(win, bd=0, highlightthickness=0),
                "right": tk.Frame(win, bd=0, highlightthickness=0),
            }
            for side, fr in ring.items():
                fr.configure(bg=_GLOW[layer])
                if side == "top":
                    fr.place(x=0, y=0, relwidth=1, height=_BASE[layer])
                elif side == "bottom":
                    fr.place(x=0, rely=1.0, y=-_BASE[layer], relwidth=1,
                             height=_BASE[layer])
                elif side == "left":
                    fr.place(x=0, y=0, width=_BASE[layer], relheight=1)
                else:
                    fr.place(relx=1.0, x=-_BASE[layer], y=0, width=_BASE[layer],
                             relheight=1)
            layers.append(ring)
        banner = tk.Label(win, text=_TEXT, bg=_BLUE, fg="white",
                          font=("Segoe UI", 11, "bold"), padx=14, pady=6)
        banner.place(relx=0.5, y=_BASE[0] + 2, anchor="n")
        wins.append((win, layers))
    # posicionamento exato por monitor (cobre offsets negativos).
    # ORDEM IMPORTA: geometry do Tk reaplica o tamanho/posição no update();
    # por isso o SetWindowPos vem DEPOIS do último update() e nada mais
    # mexe em geometria da janela depois (só frames internos no pulso).
    try:
        root.update_idletasks()
    except Exception:
        pass
    try:
        root.update()
    except Exception:
        pass
    try:  # z-order + posição exata (HWND top-level, não o filho do Tk)
        from ctypes import wintypes

        u = ctypes.windll.user32
        # c_int assinados: sem isso offsets negativos (monitores acima/esq.)
        # são truncados p/ unsigned e a janela cai na origem errada.
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_uint]
        u.SetWindowPos.restype = wintypes.BOOL
        for (win, _), (x, y, w, h) in zip(wins, _monitors()):
            try:
                # GetParent: winfo_id() é a janela INTERNA do Tk; mover/posicionar
                # deve mirar o HWND top-level (mesma correção do click-through).
                hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
                u.SetWindowPos(hwnd, -1, x, y, w, h, 0x0010 | 0x0040)
            except Exception:
                pass
    except Exception:
        pass
    for win, _ in wins:
        _make_click_through(win)

    # --- pulso do glow (larguras sobem/descem ~1.7s por ciclo) ----------------
    def _pulse(phase: int = 0, frames: int = 0) -> None:
        s = (math.sin(phase * math.pi / 14.0) + 1.0) / 2.0  # 0..1
        big = int(round(_AMP * s))
        for _win, layer_rings in wins:
            for li, ring in enumerate(layer_rings):
                d = max(2, _BASE[li] + big)
                ring["top"].place_configure(height=d)
                ring["bottom"].place_configure(height=d)
                ring["left"].place_configure(width=d)
                ring["right"].place_configure(width=d)
            for ring in layer_rings:  # redesenho imediato (sem isso o
                for fr in ring.values():  # place não repinta a tempo)
                    fr.update_idletasks()
        root.after(60, _pulse, (phase + 1) % 10_000, frames + 1)

    try:
        root.after(60, _pulse)
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
