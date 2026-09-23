"""OCR local opcional (R2, fatia 3): leitura de texto da tela sem input físico.

Complemento mensurável da UIA (§4.2 do plano): quando a árvore expõe só
moldura (provider vazio) ou o valor de um campo é ilegível, o planner pode
pedir `perceive(ocr)` e recebe fatos de texto — nunca evidência confirmada,
nunca instrução.

Backends, nesta ordem (primeiro disponível vence):
  1. `winrt` (Windows.Media.Ocr, in-box no Windows 10/11) — sem dependência
     nova quando o pacote `winrt`/`pywinrt` está instalado;
  2. binário `tesseract` no PATH (via subprocess, `--psm 6`, sem dep nova).

Sem nenhum dos dois: `available()` é False e `read()` devolve `ok=False`
com o motivo honesto — o planner recebe "OCR indisponível" como fato e
segue com UIA/visão. Nenhum texto é inventado.

Tudo aqui é só leitura (screenshot/PIL ou arquivo); nenhum mouse/teclado.
"""

from __future__ import annotations

import shutil
import time

_TESSERACT_CMD = "tesseract"


def backend() -> str:
    """Backend OCR efetivo: `winrt` | `tesseract` | `unavailable` (puro)."""
    try:
        import winrt.windows.media.ocr  # noqa: F401
        return "winrt"
    except Exception:
        pass
    if shutil.which(_TESSERACT_CMD):
        return "tesseract"
    return "unavailable"


def available() -> bool:
    """Há backend OCR local neste ambiente? (puro, testável)."""
    return backend() != "unavailable"


def status() -> dict:
    """Diagnóstico honesto p/ logs e fatos de percepção (puro)."""
    b = backend()
    if b != "unavailable":
        return {"backend": b, "available": True, "reason": ""}
    return {
        "backend": "unavailable",
        "available": False,
        "reason": "sem backend OCR (tesseract no PATH ou pacote winrt p/ Media.Ocr)",
    }


def _to_png_bytes(image) -> bytes:
    """PIL Image | caminho | bytes -> PNG bytes. Erro honesto se inválido."""
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    try:
        from pathlib import Path

        p = Path(str(image))
        if p.is_file():
            return p.read_bytes()
    except Exception:
        pass
    try:
        import io

        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        raise ValueError(f"OCR: imagem inválida ({e})")


def _read_tesseract(png: bytes, lang: str) -> str:
    """OCR via binário tesseract (subprocess, sem dep nova)."""
    import os
    import subprocess
    import tempfile

    langs = "por+eng" if (lang or "").lower().startswith("pt") else "eng"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png)
        src = f.name
    try:
        r = subprocess.run(
            [_TESSERACT_CMD, src, "stdout", "-l", langs, "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        try:
            os.unlink(src)
        except Exception:
            pass
    if r.returncode != 0:
        raise RuntimeError(f"tesseract falhou (code={r.returncode}): {r.stderr[:200]}")
    return r.stdout or ""


def _read_winrt(png: bytes, lang: str) -> str:
    """OCR via Windows.Media.Ocr (in-box; exige pacote winrt instalado)."""
    import asyncio

    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    async def _run() -> str:
        langs = list(OcrEngine.available_recognizer_languages)
        pick = None
        want = (lang or "pt").lower()[:2]
        for lg in langs:
            try:
                tag = str(lg.language_tag or "").lower()
            except Exception:
                tag = ""
            if tag.startswith(want):
                pick = lg
                break
        if pick is not None:
            engine = OcrEngine.try_create_from_language(pick)
        else:
            engine = OcrEngine.try_create_from_user_profile_languages()
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(png)
        await writer.store_async()
        await writer.flush_async()
        stream.seek(0)
        from winrt.windows.graphics.imaging import BitmapDecoder

        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        try:
            return result.text or ""
        except Exception:
            return str(getattr(result, "text", "") or "")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result(timeout=30)
    return asyncio.run(_run())


def read(image, lang: str = "pt") -> dict:
    """Lê texto da imagem. Retorna dict (nunca levanta por falta de backend).

    `{"ok", "text", "backend", "ms", "reason"}` — `ok=False` com `reason`
    honesto quando indisponível/falha; o chamador vira isso em fato de
    percepção ("OCR indisponível"), nunca em evidência nem em erro fatal.
    """
    t0 = time.perf_counter()
    b = backend()
    if b == "unavailable":
        st = status()
        return {"ok": False, "text": "", "backend": b,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "reason": str(st.get("reason", "OCR indisponível"))}
    try:
        png = _to_png_bytes(image)
    except ValueError as e:
        return {"ok": False, "text": "", "backend": b,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "reason": str(e)[:200]}
    try:
        text = _read_winrt(png, lang) if b == "winrt" else _read_tesseract(png, lang)
    except Exception as e:
        return {"ok": False, "text": "", "backend": b,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "reason": f"OCR ({b}) falhou: {e}"[:200]}
    ms = round((time.perf_counter() - t0) * 1000, 1)
    norm = " ".join(str(text or "").split())
    if not norm:
        return {"ok": False, "text": "", "backend": b, "ms": ms,
                "reason": "OCR não encontrou texto legível na captura"}
    return {"ok": True, "text": norm[:2000], "backend": b, "ms": ms, "reason": ""}
