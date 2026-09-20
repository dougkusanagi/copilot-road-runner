"""Skills F5: catálogo compacto → skill do modelo → referências (§5.2).

- Diretórios: skills/<nome>/SKILL.md, references/, scripts/, assets/.
- Manifesto (manifest.json): nome, versão, descrição, condições de uso,
  ferramentas necessárias, modo GUI/CLI, schemas de argumentos, efeitos e
  verificações. Catálogo compacto no prompt; referências sob demanda
  (nunca todas as skills; busca explícita por orçamento).
- Executor CLI restrito (piloto Blender): subprocess com argv (sem shell),
  cwd delimitado, timeout e cancelamento; valida paths/argumentos e
  conserva stdout/stderr/artefatos. Nunca abre shell arbitrário como efeito
  colateral de instalar skill. Script novo não ganha confiança por estar
  num SKILL.md. Sem subagentes no mesmo desktop.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS_DIR = ROOT / "skills"

ALLOWED_CWD_ROOTS = ("blender-jobs", "runs")


def list_skills() -> list[dict]:
    """Catálogo compacto (nome, versão, quando-usar, modo)."""
    out = []
    if not SKILLS_DIR.is_dir():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        man = d / "manifest.json"
        if not man.is_file():
            continue
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
            out.append({"name": m.get("name", d.name),
                        "version": m.get("version", "?"),
                        "when": m.get("when", "")[:160],
                        "mode": m.get("mode", "GUI")})
        except Exception:
            continue
    return out


def catalog_text(budget: int = 8) -> str:
    """Uma linha por skill (orçamento: no máximo `budget` entradas)."""
    skills = list_skills()[:max(1, budget)]
    if not skills:
        return "(nenhuma skill instalada)"
    return "\n".join(f'- {s["name"]} [{s["mode"]}] v{s["version"]}: {s["when"]}'
                     for s in skills)


def load_skill(name: str, with_references: bool = False) -> dict:
    """Carrega SKILL.md (+ references/ sob demanda). Erro honesto se ausente."""
    safe = "".join(c for c in (name or "") if c.isalnum() or c in ("-", "_"))[:40]
    if not safe:
        raise ValueError("skill sem nome")
    d = SKILLS_DIR / safe
    doc = d / "SKILL.md"
    man = d / "manifest.json"
    if not doc.is_file() or not man.is_file():
        raise ValueError(f"skill ausente: {safe}")
    m = json.loads(man.read_text(encoding="utf-8"))
    body = doc.read_text(encoding="utf-8")
    refs: dict[str, str] = {}
    if with_references:
        refdir = d / "references"
        if refdir.is_dir():
            for f in sorted(refdir.glob("*.md"))[:10]:
                try:
                    refs[f.name] = f.read_text(encoding="utf-8")[:4000]
                except Exception:
                    pass
    return {"manifest": m, "doc": body[:6000], "references": refs}


def validate_skill_args(manifest: dict, args: dict) -> None:
    """Valida argumentos contra o schema da skill (sem executar nada)."""
    schema = manifest.get("args_schema", {}) or {}
    for req in manifest.get("required_args", []) or []:
        if req not in (args or {}):
            raise ValueError(f"skill {manifest.get('name')}: falta arg {req!r}")
    for k, rule in schema.items():
        if k not in (args or {}):
            continue
        v = args[k]
        allowed = rule.get("enum")
        if allowed is not None and v not in allowed:
            raise ValueError(f"skill arg {k}={v!r} fora de {allowed}")
        mx = rule.get("max_len")
        if isinstance(v, str) and isinstance(mx, int) and len(v) > mx:
            raise ValueError(f"skill arg {k} excede {mx} chars")


def run_cli_skill(skill_name: str, args: dict, timeout_s: float = 120.0) -> dict:
    """Executor CLI restrito: receita parametrizada, sem shell arbitrário.

    - skill deve ser mode=CLI com manifest.scripts mapeando receita->script.
    - argv montado pelo Python (nunca shell=True); cwd dentro de
      ALLOWED_CWD_ROOTS; timeout + cancelamento (safety); paths validados.
    - conserva stdout/stderr/artefatos p/ verificação (render incluso).
    """
    import safety

    loaded = load_skill(skill_name)
    man = loaded["manifest"]
    if man.get("mode") != "CLI":
        raise ValueError(f"skill {skill_name} não é CLI (mode={man.get('mode')})")
    validate_skill_args(man, args or {})
    recipe = str((args or {}).get("recipe", ""))
    scripts = man.get("scripts", {}) or {}
    if recipe not in scripts:
        raise ValueError(f"receita {recipe!r} ausente em {skill_name}; "
                         f"use uma de {sorted(scripts)}")
    script = (SKILLS_DIR / skill_name / "scripts" / scripts[recipe]).resolve()
    root = SKILLS_DIR.resolve()
    if root not in script.parents and script != root:
        raise ValueError("script fora da skill (path traversal vetado)")
    if not script.is_file():
        raise ValueError(f"script ausente: {script.name} (dependência ausente?)")
    cwd_name = str((args or {}).get("cwd", ALLOWED_CWD_ROOTS[0]))
    if cwd_name not in ALLOWED_CWD_ROOTS and not cwd_name.startswith("runs"):
        raise ValueError(f"cwd {cwd_name!r} fora de {ALLOWED_CWD_ROOTS}")
    cwd = (ROOT / cwd_name).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    argv = [str(script)]
    for k in man.get("arg_order", []) or []:
        if k in ("recipe", "cwd"):
            continue
        if k in (args or {}):
            argv.append(f"--{k}={args[k]}")
    try:
        proc = subprocess.Popen([str(p) for p in argv], cwd=str(cwd),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
    except Exception as e:
        raise RuntimeError(f"skill CLI não iniciou: {e}")
    try:
        outs, errs = proc.communicate(timeout=max(1.0, timeout_s))
        if safety.stop_requested():
            return {"ok": False, "cancelled": True, "stdout": outs[-2000:],
                    "stderr": errs[-2000:], "code": proc.returncode}
        return {"ok": proc.returncode == 0, "code": proc.returncode,
                "stdout": (outs or "")[-4000:], "stderr": (errs or "")[-4000:],
                "cwd": str(cwd)}
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        outs, errs = proc.communicate()
        return {"ok": False, "timeout": True, "stdout": (outs or "")[-2000:],
                "stderr": (errs or "")[-2000:], "code": proc.returncode}
