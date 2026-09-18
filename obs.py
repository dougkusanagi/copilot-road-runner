"""Observação: screenshot rápida via mss + resize via Pillow."""
from __future__ import annotations

import time
from pathlib import Path

import mss
from PIL import Image

LAST_PNG = Path("last.png")
# Largura máxima enviada ao VLM. Configurável via config.json (screenshot_max_width).
VLM_MAX_WIDTH = 1280


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


def downscale_for_vlm(
    src: str | Path = LAST_PNG,
    max_width: int = VLM_MAX_WIDTH,
    jpeg_quality: int = 60,
) -> tuple[str, tuple[int, int]]:
    """Gera versão reduzida p/ VLM. Retorna (path, (w,h))."""
    import io
    import base64

    src = Path(src)
    img = Image.open(src).convert("RGB")
    w, h = img.size
    if w > max_width:
        new_h = int(h * max_width / w)
        img = img.resize((max_width, new_h), Image.LANCZOS)
        w, h = img.size
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return b64, (w, h)


def screenshot_b64_for_vlm(max_width: int = VLM_MAX_WIDTH) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """Atalho: captura + retorna (b64, vlm_size, real_size)."""
    path, real_size = take_screenshot()
    b64, vlm_size = downscale_for_vlm(path, max_width=max_width)
    return b64, vlm_size, real_size


if __name__ == "__main__":
    t0 = time.perf_counter()
    p, (w, h) = take_screenshot()
    dt = (time.perf_counter() - t0) * 1000
    print(f"saved={p} size={w}x{h} in {dt:.0f}ms")
