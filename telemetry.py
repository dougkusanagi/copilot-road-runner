"""Telemetria F0: ambiente, tempos e runs reproduzíveis (§9.1).

Uso normal continua local; este módulo só coleta fatos e grava
`runs/<id>/` (gitignored): JSONL de passos, summary, config/revisões,
timings, decisões e evidências. Não versiona capturas/prompts completos
salvo em modo diagnóstico explícito (com retenção/limpeza).

Não interpreta o pedido nem escolhe ações: só mede e registra.
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"


def collect_env() -> dict:
    """GPU, driver, backend, RAM, CPU, resolução e carga de apps (§1)."""
    import psutil

    env: dict = {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_total_gb": round(psutil.virtual_memory().total / 1e9, 2),
        "ram_pct": round(psutil.virtual_memory().percent, 1),
        "cpu_pct": psutil.cpu_percent(interval=0.1),
        "python": platform.python_version(),
    }
    # Resolução virtual (multi-monitor) — best-effort, nunca quebra.
    try:
        import ctypes

        u = ctypes.windll.user32
        env["screen"] = {
            "origin": [u.GetSystemMetrics(76), u.GetSystemMetrics(77)],
            "size": [u.GetSystemMetrics(78), u.GetSystemMetrics(79)],
        }
    except Exception:
        env["screen"] = {}
    env["gpu"] = _gpu_info()
    return env


def _gpu_info() -> dict:
    """VRAM dedicada/compartilhada e offload efetivo (best-effort)."""
    info: dict = {"backend": "unknown", "dedicated_mb": None,
                  "shared_mb": None, "detail": "n/a"}
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,"
             "memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        line = out.stdout.strip().splitlines()
        if line:
            parts = [p.strip() for p in line[0].split(",")]
            if len(parts) >= 5:
                info.update({"backend": "cuda/nvidia-smi", "name": parts[0],
                             "driver": parts[1],
                             "dedicated_mb": _num(parts[2]),
                             "used_mb": _num(parts[3]),
                             "free_mb": _num(parts[4]),
                             "detail": line[0][:200]})
                return info
    except Exception as e:
        info["detail"] = f"sem nvidia-smi: {e}"[:200]
    return info


def _num(s: str) -> float | None:
    try:
        return float(s)
    except Exception:
        return None


def p50(xs: list[float]) -> float:
    return round(statistics.median(xs), 1) if xs else 0.0


def p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(0.95 * len(s)))], 1)


def new_run_id(prefix: str = "run") -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = RUNS_DIR / f"{prefix}-{ts}"
    cand = base
    i = 0
    while cand.exists():
        i += 1
        cand = Path(f"{base}-{i}")
    cand.mkdir(parents=True, exist_ok=True)
    return cand.name


def run_dir(run_id: str) -> Path:
    d = RUNS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def append_jsonl(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def summarize_steps(events: list[dict]) -> dict:
    """Tempos por fase + taxa de timeout/falha (falhas nunca escondidas na média)."""
    def col(key: str) -> list[float]:
        out = []
        for e in events:
            t = (e.get("timings") or {}).get(key)
            if isinstance(t, (int, float)):
                out.append(float(t))
        return out

    timeouts = sum(1 for e in events if "timeout" in str(
        e.get("error", "") + e.get("verify", "")).lower())
    fails = [e for e in events if e.get("event") in ("retry", "stuck", "refused")]
    ok = [e for e in events if "did" in e]
    return {
        "steps": len(ok),
        "retries": sum(1 for e in events if e.get("event") == "retry"),
        "fail_events": len(fails),
        "timeout_events": timeouts,
        "planner_ms": {"p50": p50(col("planner_ms")), "p95": p95(col("planner_ms"))},
        "vision_ms": {"p50": p50(col("vision_ms")), "p95": p95(col("vision_ms"))},
        "uia_ms": {"p50": p50(col("uia_ms")), "p95": p95(col("uia_ms"))},
    }
