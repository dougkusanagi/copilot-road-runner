"""Observação: screenshot rápida via mss + resize via Pillow."""
from __future__ import annotations

import time
from pathlib import Path

import mss
from PIL import Image

LAST_PNG = Path("last.png")


def take_screenshot(
    dest: str | Path = LAST_PNG,
    max_width: int | None = None,
    jpeg_quality: int = 60,
) -> tuple[str, tuple[int, int]]:
    """Captura monitor primário, salva PNG full-res, retorna (path, (w,h))."""
    dest = Path(dest)
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    w, h = img.size
    img.save(dest)
    return str(dest), (w, h)


def _foreground_rect() -> tuple[int, int, int, int] | None:
    """Rect da janela ativa (left, top, right, bottom) ou None."""
    try:
        import ctypes

        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        if not h:
            return None
        r = (ctypes.c_long * 4)()
        if not u.GetWindowRect(h, r):
            return None
        l, t, rr, b = (r[0], r[1], r[2], r[3])
        if rr - l < 50 or b - t < 50:
            return None
        return (l, t, rr, b)
    except Exception:
        return None


def capture_for_vision(
    max_long_edge: int = 1024,
) -> tuple["Image.Image", tuple[int, int], tuple[int, int]]:
    """Captura SÓ quando a visão é necessária (chamar só no branch visual).

    Prefere a janela ativa (crop preservando offset); senão monitor primário.
    Retorna (PIL.Image, origin_xy, full_size). Coordenadas do Vocaela (0..1)
    são relativas à imagem retornada → some origin_xy ao converter p/ físico.
    Aspect ratio sempre preservado (sem stretch).
    """
    import mss as _mss

    with _mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])
        full = Image.frombytes("RGB", shot.size, shot.rgb)
    fw, fh = full.size
    rect = _foreground_rect()
    if rect:
        l, t, rr, b = rect
        l = max(0, l)
        t = max(0, t)
        rr = min(fw, rr)
        b = min(fh, b)
        if rr - l >= 50 and b - t >= 50:
            return full.crop((l, t, rr, b)), (l, t), (fw, fh)
    return full, (0, 0), (fw, fh)


if __name__ == "__main__":
    t0 = time.perf_counter()
    p, (w, h) = take_screenshot()
    dt = (time.perf_counter() - t0) * 1000
    print(f"saved={p} size={w}x{h} in {dt:.0f}ms")
