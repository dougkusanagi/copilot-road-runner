"""R3: bateria de probes — integridade offline + agregação (sem rede)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.probe_battery import classify_error, load_battery, run_battery, summarize  # noqa: E402
from planner import PlannerActionType, PlannerDecision  # noqa: E402


class _FakePlanner:
    def __init__(self, decisions=None, error=None):
        self._decisions = list(decisions or [])
        self._error = error

    def next_action(self, **kwargs):
        if self._error is not None:
            raise self._error
        if self._decisions:
            return self._decisions.pop(0), 12.5
        return PlannerDecision(type="wait", ms=10), 12.5


class TestBatteryIntegrity(unittest.TestCase):
    def test_30_cenas_unicas_com_arquivos(self):
        from evals.probes import FIXTURES

        bat = load_battery()
        scenes = bat["scenes"]
        self.assertEqual(len(scenes), 30)
        self.assertEqual(len(set(scenes)), 30)
        for s in scenes:
            self.assertTrue((FIXTURES / f"{s}.json").is_file(), s)

    def test_tipos_validos_no_contrato(self):
        from evals.probes import load_fixture

        allowed = set(PlannerActionType.__args__)
        for s in load_battery()["scenes"]:
            fx = load_fixture(s)
            for t in fx.get("valid_next_types", []):
                self.assertIn(t, allowed, f"{s}:{t}")
            self.assertTrue(fx["goal"] and fx["window"])


class TestSummarize(unittest.TestCase):
    def test_taxas_latencias_e_gate(self):
        rows = [
            {"scene": "a", "rep": 0, "pass": True, "elapsed_ms": 100.0},
            {"scene": "a", "rep": 1, "pass": True, "elapsed_ms": 50.0},
            {"scene": "b", "rep": 0, "pass": False, "elapsed_ms": 200.0,
             "errors": ["tipo 'open_app' não avança"]},
            {"scene": "b", "rep": 1, "pass": True, "elapsed_ms": 60.0},
        ]
        s = summarize(rows, "B1", "M", "test")
        self.assertEqual(s["calls"], 4)
        self.assertEqual(s["pass_rate"], 0.75)
        self.assertEqual(s["format_valid_rate"], 1.0)
        self.assertEqual(s["latency_ms"]["p50"], 100.0)
        self.assertFalse(s["gate_pass"])  # 75% < 90%
        ok = summarize(
            [{"scene": "a", "rep": i, "pass": True, "elapsed_ms": 10.0}
             for i in range(10)], "B1", "M", "test")
        self.assertTrue(ok["gate_pass"])

    def test_coord_attempt_conta_invariante(self):
        rows = [{"scene": "a", "rep": 0, "pass": False, "elapsed_ms": None,
                 "error_kind": "format",
                 "error": "ValueError: planner emitiu coordenadas (proibido)"}]
        s = summarize(rows, "B1", "M", "test")
        self.assertEqual(s["coord_attempts"], 1)
        self.assertFalse(s["gate_pass"])

    def test_classify_error(self):
        self.assertEqual(classify_error(ValueError("planner não retornou JSON")), "format")
        self.assertEqual(classify_error(RuntimeError("planner HTTP falhou: connect")), "infra")
        self.assertEqual(classify_error(KeyError("x")), "error")


class TestRunBatteryOffline(unittest.TestCase):
    def test_fake_planner_sem_rede(self):
        from evals.probes import load_fixture

        fx = load_fixture("calc-aberta")
        rows = run_battery(
            _FakePlanner([PlannerDecision(type="uia_click", target="Sete")]),
            ["calc-aberta"], reps=1)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["pass"])
        self.assertEqual(rows[0]["key"], "uia_click")
        self.assertEqual(fx["id"], "calc-aberta")

    def test_erro_nao_quebra_bateria(self):
        rows = run_battery(_FakePlanner(error=ValueError("não retornou JSON")),
                           ["calc-aberta", "uia-vazia"], reps=1)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not r["pass"] for r in rows))
        self.assertTrue(all(r["error_kind"] == "format" for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
