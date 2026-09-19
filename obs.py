"""Observação: screenshot rápida via mss + resize via Pillow."""
from __future__ import annotations

import time
from pathlib import Path

import mss
from PIL import Image

LAST_PNG = Path("last.png")


def _grab_virtual() -> tuple[Image.Image, tuple[int, int]]:
    """Captura o DESKTOP VIRTUAL inteiro (todos os monitores).

    Retorna (imagem, (left, top)): o pixel (0,0) da imagem corresponde à
    coordenada de tela (left, top) — negativa se houver monitor à
    esquerda/acima do primário. mss.monitors[0] é a caixa envolvente de
    todos, não o primário.
    """
    with mss.mss() as sct:
        mon = sct.monitors[0]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    return img, (int(mon["left"]), int(mon["top"]))


def take_screenshot(dest: str | Path = LAST_PNG) -> tuple[str, tuple[int, int]]:
    """Captura o desktop virtual, salva PNG full-res, retorna (path, (w,h))."""
    dest = Path(dest)
    img, _ = _grab_virtual()
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
        left, top, right, bottom = (r[0], r[1], r[2], r[3])
        if right - left < 50 or bottom - top < 50:
            return None
        return (left, top, right, bottom)
    except Exception:
        return None


def capture_for_vision(
    max_long_edge: int = 1024,
) -> tuple["Image.Image", tuple[int, int], tuple[int, int]]:
    """Captura SÓ quando a visão é necessária (chamar só no branch visual).

    Prefere a janela ativa (crop preservando offset); senão o desktop
    virtual inteiro. Retorna (PIL.Image, origin_xy, full_size), com
    origin_xy em COORDENADAS DE TELA (pode ser negativo em multi-monitor):
    as coordenadas do Vocaela (0..1) são relativas à imagem retornada →
    `origin + frac * size` dá o pixel físico. Aspect ratio preservado.
    """
    full, (vx, vy) = _grab_virtual()
    return crop_to_rect(full, (vx, vy), _foreground_rect())


def crop_to_rect(full: Image.Image, virtual_origin: tuple[int, int],
                 rect: tuple[int, int, int, int] | None,
                 ) -> tuple[Image.Image, tuple[int, int], tuple[int, int]]:
    """Recorta `rect` (coords de tela) de `full`, cujo (0,0) é `virtual_origin`.

    Puro (sem GUI) p/ teste. Retorna (crop, origin_tela, full_size).
    """
    fw, fh = full.size
    vx, vy = virtual_origin
    if rect:
        left, top, right, bottom = rect
        # tela -> pixel da imagem, limitado à imagem
        pl, pt = max(0, left - vx), max(0, top - vy)
        pr, pb = min(fw, right - vx), min(fh, bottom - vy)
        if pr - pl >= 50 and pb - pt >= 50:
            return full.crop((pl, pt, pr, pb)), (pl + vx, pt + vy), (fw, fh)
    return full, (vx, vy), (fw, fh)


if __name__ == "__main__":
    t0 = time.perf_counter()
    p, (w, h) = take_screenshot()
    dt = (time.perf_counter() - t0) * 1000
    print(f"saved={p} size={w}x{h} in {dt:.0f}ms")
