"""Bateria de probes R3 (§6.1): N cenas x R reps contra planner real.

Só chama `planner.next_action` (texto; no perfil unificado inclui leitura
de screenshot). NUNCA mouse/teclado/execute — seguro no host. Não salva
screenshots nem prompts por padrão (só decisões + métricas).

Uso:
  uv run python -m evals.probe_battery --profile B1 --reps 3
  uv run python -m evals.probe_battery --profile B1 --scenes uia-vazia,modal-dialog --reps 1
  uv run python -m evals.probe_battery --profile B1 --no-runtime --diagnostic

Saída: runs/probe-<profile>-<ts>/rows.jsonl + summary.json (runs/ é gitignored).
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
from evals.probes import check_decision, load_fixture

BATTERY_JSON = ROOT / "evals" / "battery.json"


def load_battery() -> dict:
    return json.loads(BATTERY_JSON.read_text(encoding="utf-8"))


def classify_error(e: Exception) -> str:
    """format = JSON/coords/enum (culpa do modelo); infra = rede/servidor."""
    msg = f"{type(e).__name__}: {e}"
    if isinstance(e, ValueError) or "JSON" in msg or "coordenadas" in msg:
        return "format"
    if "HTTP" in msg or "connect" in msg.lower() or "timeout" in msg.lower():
        return "infra"
    return "error"


def summarize(rows: list[dict], profile: str, model: str, battery: str) -> dict:
    """Agregação pura (testável sem rede): taxas, latências e gate §6.1."""
    calls = [r for r in rows if r.get("error_kind") in (None, "")]
    errs = [r for r in rows if r.get("error_kind")]
    lat = sorted(r["elapsed_ms"] for r in calls if r.get("elapsed_ms") is not None)
    warm = sorted(
        r["elapsed_ms"] for r in calls
        if r.get("elapsed_ms") is not None and int(r.get("rep", 0)) > 0
    )

    def pct(data: list[float], q: float) -> float:
        if not data:
            return 0.0
        i = min(len(data) - 1, int(q * len(data)))
        return round(float(data[i]), 1)

    passed = sum(1 for r in calls if r.get("pass"))
    fmt_ok = sum(1 for r in calls if r.get("format_valid", True))
    coord = sum(1 for r in rows if r.get("error_kind") == "format"
                and "coordenad" in str(r.get("error", "")))
    n_calls = len(calls)
    by_scene: dict[str, dict] = {}
    for r in calls:
        s = by_scene.setdefault(r["scene"], {"pass": 0, "total": 0})
        s["total"] += 1
        s["pass"] += 1 if r.get("pass") else 0
    gate = {
        "valid_ge_90": (passed / n_calls >= 0.90) if n_calls else False,
        "format_ge_99": (fmt_ok / n_calls >= 0.99) if n_calls else False,
        "zero_coord_attempts": coord == 0,
    }
    return {
        "battery": battery,
        "profile": profile,
        "model": model,
        "scenes": len(by_scene),
        "reps": max((int(r.get("rep", 0)) for r in rows), default=-1) + 1,
        "calls": n_calls,
        "errors": len(errs),
        "pass_rate": round(passed / n_calls, 3) if n_calls else 0.0,
        "format_valid_rate": round(fmt_ok / n_calls, 3) if n_calls else 0.0,
        "coord_attempts": coord,
        "latency_ms": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95)},
        "latency_warmed_ms": {"p50": pct(warm, 0.5), "p95": pct(warm, 0.95)},
        "by_scene": by_scene,
        "gate_provisional": gate,
        "gate_pass": all(gate.values()),
    }


def run_battery(planner, scenes: list[str], reps: int, delay_s: float = 0.0) -> list[dict]:
    """Sequencial (nunca concorrente: evita estouro de KV cache)."""
    rows: list[dict] = []
    for scene in scenes:
        fx = load_fixture(scene)
        for rep in range(reps):
            row: dict = {"scene": scene, "rep": rep}
            try:
                dec, ms = planner.next_action(
                    goal=fx["goal"],
                    window=fx["window"],
                    ui_names=list(fx.get("ui_names", [])),
                    history=[],
                    task_summary=fx.get("task_summary", ""),
                    last_result=fx.get("last_result", ""),
                )
                res = check_decision(fx, dec)
                row.update({"pass": res["pass"], "key": res["key"],
                            "type": dec.type, "errors": res["errors"],
                            "elapsed_ms": round(ms, 1), "format_valid": True})
            except Exception as e:  # noqa: BLE001 — probe registra, não quebra
                kind = classify_error(e)
                row.update({"pass": False, "key": "", "type": "",
                            "errors": [f"{kind}: {e}"[:200]],
                            "elapsed_ms": None, "format_valid": kind != "format",
                            "error_kind": kind, "error": str(e)[:200]})
            rows.append(row)
            if delay_s:
                time.sleep(delay_s)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Bateria de probes sem inputs físicos")
    ap.add_argument("--profile", default="B1")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--scenes", default="",
                    help="ids separados por vírgula ou fatio a:b (1-based)")
    ap.add_argument("--slice", default="", help="fatio de cenas a:b (1-based, fim exclusivo)")
    ap.add_argument("--no-runtime", action="store_true",
                    help="não subir servidores; usa endpoints vivos")
    ap.add_argument("--diagnostic", action="store_true",
                    help="inclui prompts completos nas linhas (retenção explícita)")
    ap.add_argument("--delay-s", type=float, default=0.0)
    args = ap.parse_args()

    import config as cfgmod
    import server as srvmod
    from model_adapters import build_adapters

    bat = load_battery()
    scenes = list(bat["scenes"])
    if args.scenes:
        want = [s.strip() for s in args.scenes.split(",") if s.strip()]
        scenes = [s for s in scenes if s in want]
        if not scenes:
            print(f"nenhuma cena válida em: {args.scenes}")
            raise SystemExit(2)
    if args.slice:
        a, _, b = args.slice.partition(":")
        scenes = scenes[int(a or 0): int(b or len(scenes))]
    cfg = cfgmod.load("config.json")
    cfgmod.apply_profile(cfg, args.profile)

    procs: dict = {}
    if not args.no_runtime:
        from loop import _ensure_local_servers

        procs = _ensure_local_servers(cfg)
    try:
        planner, _vision, prof = build_adapters(cfg)
        st = planner.check()
        if not st.get("ok"):
            print(f"planner OFFLINE: {st.get('error')}")
            raise SystemExit(3)
        model = str(planner.model)
        print(f"perfil={prof.get('name')} modelo={model} cenas={len(scenes)} reps={args.reps}")
        t0 = time.perf_counter()
        rows = run_battery(planner, scenes, max(1, args.reps), delay_s=args.delay_s)
        total_s = round(time.perf_counter() - t0, 1)
    finally:
        try:
            srvmod.stop_servers(procs)
        except Exception:
            pass

    run_id = tel.new_run_id(f"probe-{args.profile.upper()}")
    d = tel.run_dir(run_id)
    keep_prompts = bool(args.diagnostic)
    for r in rows:
        tel.append_jsonl(d / "rows.jsonl",
                         r if keep_prompts else {k: v for k, v in r.items()})
    summary = summarize(rows, args.profile.upper(), model, bat.get("battery", ""))
    summary.update({"total_s": total_s, "run_id": run_id,
                    "endpoint_models": st.get("models"),
                    "env": tel.collect_env()})
    tel.write_json(d / "summary.json", summary)
    if not keep_prompts:
        (d / "note.txt").write_text(
            "screenshots/prompts completos só com --diagnostic\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
