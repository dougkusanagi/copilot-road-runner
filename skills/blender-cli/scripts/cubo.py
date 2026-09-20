"""Receita piloto: cubo parametrizado (delimitada, sem shell).

Uso restrito via skills.run_cli_skill (argv, cwd delimitado, timeout).
Fora do Blender real este script grava um marcador .blend + PNG mínimo
p/ verificação do pipeline; com Blender instalado, trocar o corpo por
`blender --background --python` equivalente (mesmos argv).
"""
import argparse
import struct
import zlib
from pathlib import Path


def _png_minimo(path: Path) -> None:
    w = h = 8
    raw = b"".join(b"\x00" + b"\x80\x80\xff" * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(
            ">I", zlib.crc32(c) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(
        ">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tamanho", default="2")
    a = ap.parse_args()
    cwd = Path(".").resolve()
    (cwd / f"cubo-t{a.tamanho}.blend").write_text(
        f"piloto cubo tamanho={a.tamanho}\n", encoding="utf-8")
    _png_minimo(cwd / f"cubo-t{a.tamanho}.png")
    print(f"cubo ok tamanho={a.tamanho}")


if __name__ == "__main__":
    main()
