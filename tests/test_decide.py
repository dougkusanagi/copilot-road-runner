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
            "abra o Edge e busque preco RTX 4060",
            5,
            {"hist_labels": []},
            CFG,
            planner=_FakePlanner(PlannerDecision(type="open_app", app="msedge")),
            vocaela=_NoVision(),
        )
        self.assertEqual(dec.action.type, "open")
        self.assertEqual(dec.action.target, "msedge")
        self.assertEqual(dec.source, "planner")
        self.assertEqual(tm["planner_calls"], 1)

    def test_bootstrap_notepad_step0_abre(self):
        # janela errada + step 0 → bootstrap open notepad.exe (sem focus real).
        self._patch_snapshot([], "Edge", None)
        dec, _ = loop.decide(
            "abra o notepad",
            0,
            {"hist_labels": []},
            CFG,
            planner=_FakePlanner(PlannerDecision(type="done")),
            vocaela=_NoVision(),
        )
        self.assertEqual(dec.action.type, "open")
        self.assertEqual(dec.action.target, "notepad.exe")

    def test_janela_certa_pula_bootstrap(self):
        # janela certa → bootstrap None, decisão nativa do planner passa direto.
        self._patch_snapshot([], "Bloco de Notas - Notepad", None)
        dec, _ = loop.decide(
            "abra o notepad",
            3,
            {"hist_labels": []},
            CFG,
            planner=_FakePlanner(PlannerDecision(type="type_text", text="Hello")),
            vocaela=_NoVision(),
        )
        self.assertEqual(dec.action.type, "type")
        self.assertEqual(dec.action.text, "Hello")

    def test_uia_click_resolve_sem_vision(self):
        items = [{"id": 0, "name": "Sete", "type": "Button", "bounds": [10, 10, 50, 50]}]
        self._patch_snapshot(items, "Calculadora", (0, 0, 400, 400))
        dec, tm = loop.decide(
            "na calculadora clique no Sete",
            2,
            {"hist_labels": []},
            CFG,
            planner=_FakePlanner(PlannerDecision(type="uia_click", target="Sete")),
            vocaela=_NoVision(),
        )
        self.assertEqual(dec.source, "uia")
        self.assertEqual((dec.action.x, dec.action.y), (30, 30))
        self.assertEqual(tm.get("vision_calls", 0), 0)

    def test_done_sem_acao_recusado(self):
        # R1: `done` exige evidência de EFEITO CONFIRMADO. Janela vista ou
        # ação enviada não prova objetivo — done sem refs ou com refs
        # desconhecidas veta, mesmo que a observação exista na tela.
        self._patch_snapshot([], "Edge", None)
        with self.assertRaises(RuntimeError):
            loop.decide(
                "abra o Edge",
                2,
                {"hist_labels": []},
                CFG,
                planner=_FakePlanner(PlannerDecision(type="done")),
                vocaela=_NoVision(),
            )
        with self.assertRaises(RuntimeError):
            loop.decide(
                "abra o Edge",
                2,
                {"hist_labels": ["wait(300ms) => window 'Edge'"]},
                CFG,
                planner=_FakePlanner(PlannerDecision(type="done")),
                vocaela=_NoVision(),
            )
        import state as statemod

        st = statemod.init("abra o Edge")
        # Observação vista mas NÃO confirmada: observar não confirma (R1).
        fake_observed = "obs-abc123: window='Edge'; ui=(sem elementos expostos)"
        with self.assertRaises(RuntimeError):
            loop.decide(
                "abra o Edge",
                2,
                {
                    "hist_labels": ["opened msedge => window 'Edge'"],
                    "task_state": st,
                },
                CFG,
                planner=_FakePlanner(PlannerDecision(type="done", evidences=[fake_observed])),
                vocaela=_NoVision(),
            )
        self.assertNotIn(fake_observed, st.evidences)
        # Efeito confirmado entra na memória e autoriza o done exato.
        confirmed = "opened msedge => window 'Edge'"
        statemod.add_evidence(st, confirmed)
        dec, tm = loop.decide(
            "abra o Edge",
            2,
            {
                "hist_labels": ["opened msedge => window 'Edge'"],
                "task_state": st,
            },
            CFG,
            planner=_FakePlanner(PlannerDecision(type="done", evidences=[confirmed])),
            vocaela=_NoVision(),
        )
        self.assertEqual(dec.action.type, "done")
        self.assertEqual(dec.observation_ref, tm.get("observation_id"))

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
            "qual o preço da rtx 5090",
            3,
            {"hist_labels": ["type(rtx 5090) => window 'Amazon'"]},
            CFG,
            planner=_FakePlanner(PlannerDecision(type="answer", text="R$ 12.499")),
            vocaela=_NoVision(),
        )
        self.assertEqual(dec.action.type, "answer")
        self.assertEqual(dec.action.text, "R$ 12.499")
        self.assertEqual(dec.source, "planner")

    def test_observe_pagina_de_erro_diz_pra_voltar(self):
        from schemas import Action

        o = loop.observe(
            Action(type="open", target="chrome"), "PowerShell", "Page Not Found - Brave"
        )
        self.assertIn("ERROR page", o)
        self.assertIn("do NOT retry the same URL", o)

    def test_observe_pagina_ok_sem_hint_de_erro(self):
        from schemas import Action

        o = loop.observe(Action(type="open", target="chrome"), "PowerShell", "Amazon.com")
        self.assertNotIn("ERROR page", o)

    def test_observe_app_ja_ativo_manda_agir_dentro(self):
        from schemas import Action

        # run real 19/09: open(chrome) com 'Google Chrome' parado no seletor
        # de perfil; "no window change yet" virava loop de reabrir.
        o = loop.observe(Action(type="open", target="chrome"), "Google Chrome", "Google Chrome")
        self.assertIn("already active", o)
        self.assertIn("INSIDE", o)
        self.assertNotIn("no window change yet", o)

    def test_observe_focus_miss_mantem_sem_mudanca(self):
        from schemas import Action

        o = loop.observe(Action(type="focus", target="bloco de notas"), "Edge", "Edge")
        self.assertIn("no window change yet", o)

    def test_receita_cobre_seletor_de_perfil(self):
        import planner

        self.assertIn("profile/welcome/first-run picker", planner.PLANNER_SYSTEM)

    def test_observe_hotkey_conhecida_nao_e_falha(self):
        from schemas import Action

        # Run 20/09: ctrl+l válido era lido como "wrong combo" porque o título
        # não muda em tecla de foco — isso confundia o planner.
        o = loop.observe(
            Action(type="hotkey", key="ctrl+l"),
            "Amazon.com - Google Chrome",
            "Amazon.com - Google Chrome",
        )
        self.assertIn("expected for hotkey", o)
        self.assertNotIn("wrong combos", o)

    def test_observe_hotkey_desconhecida_aponta_receita(self):
        from schemas import Action

        o = loop.observe(Action(type="hotkey", key="ctrl+alt+n"), "N", "N")
        self.assertIn("wrong combos", o)
        self.assertIn("ctrl+t", o)

    def test_prompt_intersticial_e_uia_pobre(self):
        import planner

        blob = planner.PLANNER_SYSTEM
        self.assertIn("Continue shopping", blob)
        self.assertIn("that sub-goal is DONE", blob)
        p = planner.build_prompt(
            "abra o chrome",
            "Amazon.com - Google Chrome",
            ["Button:Minimizar", "Button:Fechar", "Window:Amazon.com"],
            ["hotkey(ctrl+t) => window 'A' -> 'B'"],
        )
        self.assertIn("visual_action", p)

    def test_guard_browser_ativo_manda_avancar(self):
        # Guarda anti-reabertura: mensagem genérica (não só ctrl+l) + avanço
        # de sub-objetivo + intersticial. Mocka planner p/ open_app com Chrome
        # já ativo e confere o last_error via exceção.
        items: list = []
        orig = loop.active_window_snapshot
        loop.active_window_snapshot = lambda: (items, "Amazon.com - Google Chrome", None)
        self.addCleanup(lambda: setattr(loop, "active_window_snapshot", orig))

        class _P:
            def next_action(
                self,
                goal,
                window,
                ui_names,
                history,
                last_error="",
                skills_catalog="",
                skill_context="",
            ):
                from planner import PlannerDecision

                return PlannerDecision(type="open_app", app="chrome"), 1.0

        class _V:
            def act_sync(self, img, instruction, history=None):
                raise AssertionError("sem visão aqui")

        with self.assertRaises(RuntimeError) as cm:
            loop.decide(
                "abra o chrome e pesquise",
                1,
                {"hist_labels": []},
                {"screenshot_max_width": 1024},
                planner=_P(),
                vocaela=_V(),
            )
        msg = str(cm.exception)
        self.assertIn("CUMPRIDA", msg)
        self.assertIn("Continue shopping", msg)
        self.assertIn("uia_click", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
