"""Receita piloto: esfera parametrizada (delimitada, sem shell)."""
import argparse
import importlib.util as _ilu
from pathlib import Path

_spec = _ilu.spec_from_file_location("cubo", str(Path(__file__).with_name("cubo.py")))
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tamanho", default="2")
    a = ap.parse_args()
    cwd = Path(".").resolve()
    (cwd / f"esfera-t{a.tamanho}.blend").write_text(
        f"piloto esfera tamanho={a.tamanho}\n", encoding="utf-8")
    _mod._png_minimo(cwd / f"esfera-t{a.tamanho}.png")
    print(f"esfera ok tamanho={a.tamanho}")


if __name__ == "__main__":
    main()
