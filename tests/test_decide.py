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
        # Navegação web é pela UI (open_app + teclado), sem teleporte p/ URL.
        self._patch_snapshot([], "Edge", None)
        dec, tm = loop.decide(
            "abra o Edge e busque preco RTX 4060", 5, {"hist_labels": []}, CFG,
            planner=_FakePlanner(PlannerDecision(type="open_app",
                                                  app="msedge")),
            vocaela=_NoVision())
        self.assertEqual(dec.action.type, "open")
        self.assertEqual(dec.action.target, "msedge")
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

    def test_done_sem_acao_recusado(self):
        # guard 4: planner diz done sem ter feito nada -> last_error, não done
        self._patch_snapshot([], "Edge", None)
        with self.assertRaises(RuntimeError):
            loop.decide("abra o Edge", 2, {"hist_labels": []}, CFG,
                        planner=_FakePlanner(PlannerDecision(type="done")),
                        vocaela=_NoVision())
        with self.assertRaises(RuntimeError):
            loop.decide("abra o Edge", 2, {"hist_labels": ["wait(300ms) => window 'Edge'"]},
                        CFG, planner=_FakePlanner(PlannerDecision(type="done")),
                        vocaela=_NoVision())
        dec, _ = loop.decide("abra o Edge", 2,
                             {"hist_labels": ["opened msedge => window 'Edge'"]}, CFG,
                             planner=_FakePlanner(PlannerDecision(type="done")),
                             vocaela=_NoVision())
        self.assertEqual(dec.action.type, "done")

    def test_observe_e_done_allowed(self):
        from schemas import Action

        self.assertFalse(loop.done_allowed([]))
        self.assertFalse(loop.done_allowed(["wait(1ms) => x", "answer(15)"]))
        self.assertTrue(loop.done_allowed(["type(5 chars) => window 'Notepad'"]))

        o = loop.observe(Action(type="open", target="notepad"), "Edge", "Bloco de Notas")
        self.assertEqual(o, "window 'Edge' -> 'Bloco de Notas'")
        o = loop.observe(Action(type="open", target="notepad"), "Edge", "Edge")
        self.assertIn("no window change yet", o)
        o = loop.observe(Action(type="type", text="Olá mundo"), "N", "N", "Olá mundo")
        self.assertIn("text visible in focused field", o)
        o = loop.observe(Action(type="type", text="Olá"), "N", "N", "outra coisa")
        self.assertIn("focused field now: 'outra coisa'", o)
        o = loop.observe(Action(type="type", text="Olá"), "N", "N", "")
        self.assertIn("unreadable", o)

    def test_sem_modelos_erro_honesto(self):
        with self.assertRaises(RuntimeError):
            loop.decide("oi", 0, {}, CFG, planner=None, vocaela=None)

    def test_answer_do_planner_vira_action(self):
        self._patch_snapshot([], "Amazon.com", None)
        dec, _ = loop.decide(
            "qual o preço da rtx 5090", 3, {"hist_labels": ["type(rtx 5090) => window 'Amazon'"]},
            CFG, planner=_FakePlanner(PlannerDecision(type="answer", text="R$ 12.499")),
            vocaela=_NoVision())
        self.assertEqual(dec.action.type, "answer")
        self.assertEqual(dec.action.text, "R$ 12.499")
        self.assertEqual(dec.source, "planner")

    def test_observe_pagina_de_erro_diz_pra_voltar(self):
        from schemas import Action

        o = loop.observe(Action(type="open", target="chrome"),
                         "PowerShell", "Page Not Found - Brave")
        self.assertIn("ERROR page", o)
        self.assertIn("do NOT retry the same URL", o)

    def test_observe_pagina_ok_sem_hint_de_erro(self):
        from schemas import Action

        o = loop.observe(Action(type="open", target="chrome"),
                         "PowerShell", "Amazon.com")
        self.assertNotIn("ERROR page", o)

    def test_observe_app_ja_ativo_manda_agir_dentro(self):
        from schemas import Action

        # run real 19/09: open(chrome) com 'Google Chrome' parado no seletor
        # de perfil; "no window change yet" virava loop de reabrir.
        o = loop.observe(Action(type="open", target="chrome"),
                         "Google Chrome", "Google Chrome")
        self.assertIn("already active", o)
        self.assertIn("INSIDE", o)
        self.assertNotIn("no window change yet", o)

    def test_observe_focus_miss_mantem_sem_mudanca(self):
        from schemas import Action

        o = loop.observe(Action(type="focus", target="bloco de notas"),
                         "Edge", "Edge")
        self.assertIn("no window change yet", o)

    def test_receita_cobre_seletor_de_perfil(self):
        import planner

        self.assertIn("profile/welcome/first-run picker", planner.PLANNER_SYSTEM)


if __name__ == "__main__":
    unittest.main(verbosity=2)
