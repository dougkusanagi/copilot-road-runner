"""Probes sem efeitos para decisões de modelos reais ou respostas gravadas.

Um probe mede se a próxima decisão é compatível com o estado observado. Ele
não executa mouse/teclado e não conta como teste end-to-end.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from planner import PlannerDecision

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "evals" / "fixtures"


def load_fixture(name: str) -> dict:
    path = FIXTURES / (name if name.endswith(".json") else f"{name}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def decision_key(decision: PlannerDecision) -> str:
    if decision.type == "hotkey":
        return f"hotkey:{(decision.keys or decision.key or '').lower()}"
    return decision.type


def check_decision(fixture: dict, decision: PlannerDecision) -> dict:
    key = decision_key(decision)
    valid_types = set(fixture.get("valid_next_types", []))
    forbidden = set(fixture.get("forbidden_repetitions", []))
    errors: list[str] = []
    if decision.type not in valid_types:
        errors.append(f"tipo {decision.type!r} não avança este estado")
    if key in forbidden:
        errors.append(f"repetição proibida: {key}")
    return {"pass": not errors, "key": key, "errors": errors}


def run_probe(planner, fixture: dict) -> tuple[dict, PlannerDecision]:
    decision, elapsed_ms = planner.next_action(
        goal=fixture["goal"],
        window=fixture["window"],
        ui_names=list(fixture.get("ui_names", [])),
        history=[],
        task_summary=fixture.get("task_summary", ""),
        last_result=fixture.get("last_result", ""),
    )
    result = check_decision(fixture, decision)
    result["elapsed_ms"] = round(elapsed_ms, 1)
    return result, decision


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe de decisão sem inputs físicos")
    parser.add_argument("fixture")
    parser.add_argument(
        "--decision", required=True, help="objeto JSON gravado; não chama modelo nem executa ações"
    )
    args = parser.parse_args()
    fixture = load_fixture(args.fixture)
    decision = PlannerDecision.model_validate(json.loads(args.decision))
    print(json.dumps(check_decision(fixture, decision), ensure_ascii=False))


if __name__ == "__main__":
    main()
