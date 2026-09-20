"""Runner F0 da bateria (§9.1–9.2): baseline B0 reproduzível sem clicar no host.

- Modelos ficam no host/GPU; cliques ficam no Sandbox (scripts existentes).
  Este runner, no host, roda em `dry_run` por padrão (bloqueia TODOS os
  efeitos, inclusive bootstrap/foco/teclado/CLI) ou em `replay` offline.
- Replay de observações é diagnóstico offline, não prova end-to-end.
- Cada execução grava `runs/<id>/`: run.jsonl, summary.json,
  config.json, env.json + checkers por tarefa. Nunca apaga o run anterior.
- Capturas/prompts completos só com --diagnostic (retenção explícita).

Uso:
  uv run python -m evals.runner --list
  uv run python -m evals.runner --pilot --dry-run
  uv run python -m evals.runner --task calc-soma --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import telemetry as tel

TASKS_JSON = ROOT / "evals" / "tasks.json"


def load_tasks() -> list[dict]:
    return json.loads(TASKS_JSON.read_text(encoding="utf-8"))["tasks"]


def check_task(task: dict, events: list[dict]) -> dict:
    """Checker independente (lê o log, não o gabarito do agente)."""
    checker = task.get("checker", "no_crash")
    dids = [e.get("did", "") for e in events if e.get("did")]
    actions = [e.get("action", {}).get("type", "") for e in events if e.get("action")]
    texts = " ".join(dids + [str(e.get("verify", "")) for e in events])
    completed = any(e.get("event") == "completion" for e in events)
    loop = any(e.get("event") == "loop" for e in events)
    base = {
        "checker": checker,
        "false_done": False,
        "loop": loop,
        "completed": completed,
        "steps": len(dids),
    }
    if checker.startswith("done_without_type_when_done"):
        typed = sum(1 for a in actions if a == "type")
        base.update({"pass": completed and typed == 0 and not loop, "typed": typed})
    elif checker.startswith("no_duplicate_type"):
        typed = sum(1 for a in actions if a == "type")
        base.update({"pass": completed and typed <= 1 and not loop, "typed": typed})
    elif checker.startswith("no_loop_on_missing"):
        blocked = any(e.get("event") == "stuck" for e in events)
        base.update(
            {"pass": blocked and not loop, "note": "alvo ausente deve terminar bloqueado sem loop"}
        )
    elif checker == "no_crash":
        base.update({"pass": None, "note": "ausência de crash não demonstra resultado"})
    elif checker.startswith("window_or_uia_contains"):
        expected = checker.split(":", 1)[1] if ":" in checker else ""
        base.update({"pass": completed and expected.lower() in texts.lower()})
    elif checker.startswith("answer_then_done"):
        answered = any(a == "answer" for a in actions)
        done = any(a == "done" for a in actions)
        expected = checker.split(":", 1)[1] if ":" in checker else ""
        base.update({"pass": answered and done and expected.lower() in texts.lower() and not loop})
    elif (
        checker.startswith("focused_text")
        or checker.startswith("uia_text")
        or checker.startswith("file_contains")
    ):
        base.update(
            {
                "pass": None,
                "note": "requer fixture/Sandbox; dry-run registra N/A",
                "text_sample": texts[:200],
            }
        )
    else:
        base.update({"pass": None, "note": "checker ainda sem oráculo independente"})
    base["false_done"] = bool(completed and base.get("pass") is False)
    return base


def load_events(path: Path) -> list[dict]:
    """Lê a trajetória completa; uma linha inválida é erro de avaliação."""
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def run_task(task: dict, cfg: dict, dry_run: bool = True, diagnostic: bool = False) -> dict:
    """Executa UMA tarefa em dry-run (sem efeitos) e grava runs/<id>/."""
    run_id = tel.new_run_id(task["id"])
    d = tel.run_dir(run_id)
    env = tel.collect_env()
    tel.write_json(d / "env.json", env)
    tel.write_json(d / "config.json", cfg)
    tel.write_json(d / "task.json", task)
    t0 = time.perf_counter()
    events: list[dict] = [{"event": "start", "task": task["id"], "dry_run": dry_run, "t": t0}]
    # Dry-run: não importa loop nem executa nada; registra o plano de
    # verificação (baseline reproduzível sem clicar no host).
    if dry_run:
        events.append(
            {
                "event": "dry_run",
                "note": "efeitos bloqueados (bootstrap/foco/teclado/CLI); "
                "cliques reais só no Sandbox",
            }
        )
    else:  # pragma: no cover — caminho com efeitos, só via Sandbox
        import loop as loopmod

        live_summary = loopmod.run(task["instruction"], cfg)
        source = ROOT / "runs" / str(live_summary.get("run_id", "")) / "run.jsonl"
        events = load_events(source)
        events.append({"event": "live_summary", "summary": live_summary})
    dt = time.perf_counter() - t0
    result = check_task(task, events)
    summary = {
        "task": task["id"],
        "dry_run": dry_run,
        "result": "dry_run_ok" if dry_run else result.get("pass"),
        "total_s": round(dt, 2),
        "check": result,
        "telemetry": tel.summarize_steps(events),
        "run_id": run_id,
    }
    for e in events:
        tel.append_jsonl(d / "run.jsonl", e)
    tel.write_json(d / "summary.json", summary)
    if not diagnostic:
        # Sem modo diagnóstico: nada de capturas/prompts completos.
        (d / "note.txt").write_text(
            "capturas/prompts completos só com --diagnostic\n", encoding="utf-8"
        )
    # Legado: mantém run.jsonl na raiz p/ compatibilidade (não apaga runs/).
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Runner F0 (dry-run por padrão)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--task", default="")
    ap.add_argument(
        "--pilot", action="store_true", help="piloto inicial: 5 tarefas pilot=true, 1 repetição"
    )
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument(
        "--live",
        action="store_true",
        help="COM efeitos (só no Sandbox, nunca no desktop de trabalho)",
    )
    ap.add_argument("--diagnostic", action="store_true")
    args = ap.parse_args()

    import config as cfgmod

    tasks = load_tasks()
    if args.list:
        for t in tasks:
            print(
                f"{t['id']:28} [{t['category']}] {'PILOT ' if t.get('pilot') else ''}"
                f"{t['instruction'][:70]}"
            )
        return
    if args.pilot:
        tasks = [t for t in tasks if t.get("pilot")][:5]
    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]
        if not tasks:
            print(f"tarefa desconhecida: {args.task}")
            raise SystemExit(2)
    if args.live and not args.task and not args.pilot:
        print("live sem filtro recusado: use --task ou --pilot no Sandbox.")
        raise SystemExit(2)
    cfg = cfgmod.load("config.json")
    for t in tasks:
        s = run_task(t, cfg, dry_run=not args.live, diagnostic=args.diagnostic)
        print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
