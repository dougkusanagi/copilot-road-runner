"""Regressão do decide (loop.py): step chega ao bootstrap sem NameError.

Cobre o bug em que `_decide_planner` usava `step` sem recebê-lo na
assinatura — em runtime todo `decide()` caía em NameError → retry → stuck.
Usa planner/vocaela fake + snapshot mockado (offline, sem GUI/modelos).

Roda com: uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loop  # noqa: E402
from planner import PlannerDecision  # noqa: E402


class _FakePlanner:
    def __init__(self, dec: PlannerDecision):
        self._dec = dec
        self.calls = 0

    def next_action(self, goal, window, ui_names, history, last_error=""):
        self.calls += 1
        return self._dec, 1.0


class _NoVision:
    def act_sync(self, img, instruction):
        raise AssertionError("vocaela não deveria ser chamado neste teste")


CFG = {"screenshot_max_width": 1024}


class TestDecideStep(unittest.TestCase):
    def _patch_snapshot(self, items, title, wrect):
        orig = loop.active_window_snapshot
        loop.active_window_snapshot = lambda: (items, title, wrect)
        self.addCleanup(lambda: setattr(loop, "active_window_snapshot", orig))

    def test_generico_thread_step_sem_nameerror(self):
        # instrução sem bootstrap (want=None): step 5 precisa chegar sem erro.
        self._patch_snapshot([], "Edge", None)
        dec, tm = loop.decide(
            "abra o Edge e busque preco RTX 4060", 5, {"hist_labels": []}, CFG,
            planner=_FakePlanner(PlannerDecision(type="open_url",
                                                 url="https://x.com")),
            vocaela=_NoVision())
        self.assertEqual(dec.action.type, "open")
        self.assertEqual(dec.source, "planner")
        self.assertEqual(tm["planner_calls"], 1)

    def test_bootstrap_notepad_step0_abre(self):
        # janela errada + step 0 → bootstrap open notepad.exe (sem focus real).
        self._patch_snapshot([], "Edge", None)
        dec, _ = loop.decide(
            "abra o notepad", 0, {"hist_labels": []}, CFG,
            planner=_FakePlanner(PlannerDecision(type="done")),
            vocaela=_NoVision())
        self.assertEqual(dec.action.type, "open")
        self.assertEqual(dec.action.target, "notepad.exe")

    def test_janela_certa_pula_bootstrap(self):
        # janela certa → bootstrap None, decisão nativa do planner passa direto.
        self._patch_snapshot([], "Bloco de Notas - Notepad", None)
        dec, _ = loop.decide(
            "abra o notepad", 3, {"hist_labels": []}, CFG,
            planner=_FakePlanner(PlannerDecision(type="type_text",
                                                 text="Hello")),
            vocaela=_NoVision())
        self.assertEqual(dec.action.type, "type")
        self.assertEqual(dec.action.text, "Hello")

    def test_uia_click_resolve_sem_vision(self):
        items = [{"id": 0, "name": "Sete", "type": "Button",
                  "bounds": [10, 10, 50, 50]}]
        self._patch_snapshot(items, "Calculadora", (0, 0, 400, 400))
        dec, tm = loop.decide(
            "na calculadora clique no Sete", 2, {"hist_labels": []}, CFG,
            planner=_FakePlanner(PlannerDecision(type="uia_click",
                                                 target="Sete")),
            vocaela=_NoVision())
        self.assertEqual(dec.source, "uia")
        self.assertEqual((dec.action.x, dec.action.y), (30, 30))
        self.assertEqual(tm.get("vision_calls", 0), 0)

    def test_sem_modelos_erro_honesto(self):
        with self.assertRaises(RuntimeError):
            loop.decide("oi", 0, {}, CFG, planner=None, vocaela=None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
