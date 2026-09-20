"""R1 (fim): união discriminada fim a fim — pergunta, percepção e conclusão.

Offline, sem GUI/modelos (snapshot mockado, planners fake). Cobre:
kind question/finish/perception vindos do planner, percepção read-only sem
input físico, teto de percepções e validadores que impedem contrabando
entre kinds (plano §4.1).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loop  # noqa: E402
import state as statemod  # noqa: E402
from planner import PlannerDecision  # noqa: E402
from schemas import Action, Decision  # noqa: E402

CFG = {"screenshot_max_width": 1024}


class _Script:
    def __init__(self, decisions: list[PlannerDecision]):
        self._decisions = list(decisions)
        self.seen: list[dict] = []

    def next_action(self, **kwargs):
        self.seen.append(dict(kwargs))
        dec = self._decisions.pop(0)
        return dec, 1.0


class _NoVision:
    def act_sync(self, img, instruction, history=None):
        raise AssertionError("sem visão neste teste")


def _snap(items, title):
    orig = loop.active_window_snapshot
    loop.active_window_snapshot = lambda: (items, title, None)
    return orig


class TestKinds(unittest.TestCase):
    def test_ask_vira_question_e_done_vira_finish(self):
        orig = _snap([], "Edge")
        try:
            ctx: dict = {"hist_labels": [], "task_state": statemod.init("g")}
            dec, _ = loop.decide(
                "g", 0, ctx, CFG,
                planner=_Script([PlannerDecision(type="ask", text="qual perfil?")]),
                vocaela=_NoVision(),
            )
            self.assertEqual((dec.kind, dec.action.type), ("question", "ask"))
            st = statemod.init("g")
            ev = "type(oi) => texto visível"
            statemod.add_evidence(st, ev)
            dec2, _ = loop.decide(
                "g", 1, {"hist_labels": ["type(oi) => x"], "task_state": st}, CFG,
                planner=_Script([PlannerDecision(type="done", evidences=[ev])]),
                vocaela=_NoVision(),
            )
            self.assertEqual((dec2.kind, dec2.action.type), ("finish", "done"))
        finally:
            loop.active_window_snapshot = orig

    def test_perceive_vira_perception_com_obs_ref(self):
        orig = _snap([], "Loja")
        try:
            ctx: dict = {"hist_labels": [], "task_state": statemod.init("ler")}
            dec, tm = loop.decide(
                "ler", 0, ctx, CFG,
                planner=_Script([PlannerDecision(type="perceive", perception="uia_refresh")]),
                vocaela=_NoVision(),
            )
        finally:
            loop.active_window_snapshot = orig
        self.assertEqual(dec.kind, "perception")
        self.assertEqual(dec.action.type, "perceive")
        self.assertEqual(dec.perception, "uia_refresh")
        self.assertEqual(dec.observation_ref, tm.get("observation_id"))

    def test_perceive_invalido_vetado_com_opcoes(self):
        orig = _snap([], "Edge")
        try:
            with self.assertRaises(RuntimeError) as cm:
                loop.decide(
                    "g", 0, {"hist_labels": []}, CFG,
                    planner=_Script([PlannerDecision(type="perceive", perception="ocr_total")]),
                    vocaela=_NoVision(),
                )
        finally:
            loop.active_window_snapshot = orig
        self.assertIn("uia_refresh", str(cm.exception))

    def test_validadores_impedem_contrabando(self):
        with self.assertRaises(ValueError):
            Decision(action=Action(type="ask", text="q?"), source="planner")  # kind action
        with self.assertRaises(ValueError):
            Decision(action=Action(type="done"), source="planner")
        with self.assertRaises(ValueError):
            Decision(action=Action(type="perceive", text="uia_refresh"), source="planner")
        with self.assertRaises(ValueError):
            Decision(action=Action(type="ask", text="q?"), source="planner", kind="finish")
        with self.assertRaises(ValueError):
            Decision(
                action=Action(type="perceive", text="uia_refresh"),
                source="planner", kind="perception",
            )  # sem spec em perception
        ok = Decision(
            action=Action(type="perceive", text="read_focused"),
            source="planner", kind="perception", perception="read_focused",
        )
        self.assertEqual(ok.kind, "perception")


class TestPerceptionRun(unittest.TestCase):
    def _snap_items(self):
        return (
            [{"id": 0, "name": "Buscar", "type": "Button", "bounds": [1, 1, 9, 9]}],
            "Loja",
            None,
        )

    def test_uia_refresh_rele_sem_input_e_sem_evidencia(self):
        import actions

        called: list = []
        orig_exec = actions._execute_inner
        actions._execute_inner = lambda *a, **k: (called.append(1), "x")[1]
        try:
            ctx: dict = {"hist_labels": [], "task_state": statemod.init("ler")}
            tm: dict = {}
            facts = loop._run_perception(
                "uia_refresh", ctx, {}, tm, snapshot_fn=lambda: self._snap_items()
            )
        finally:
            actions._execute_inner = orig_exec
        self.assertIn("uia_refresh", facts)
        self.assertIn("Buscar", facts)
        self.assertEqual(called, [])  # nenhum input físico
        self.assertEqual(ctx["task_state"].evidences, [])  # fato ≠ evidência
        self.assertEqual(tm["perception"]["spec"], "uia_refresh")
        self.assertIn("observation_id", tm["perception"])

    def test_read_focused_le_campo(self):
        ctx: dict = {"task_state": statemod.init("ler")}
        tm: dict = {}
        facts = loop._run_perception(
            "read_focused", ctx, {}, tm,
            snapshot_fn=lambda: ([], "Loja", None),
            focused_fn=lambda: "rtx 5090",
        )
        self.assertIn("rtx 5090", facts)

    def test_teto_de_percepcoes(self):
        ctx: dict = {"n_perceptions": 6}
        with self.assertRaises(RuntimeError) as cm:
            loop._check_perception_budget(ctx, {})
        self.assertIn("6", str(cm.exception))
        loop._check_perception_budget({"n_perceptions": 5}, {})  # abaixo: ok
        loop._check_perception_budget({}, {"perception": {"max_perceptions": 1}})

    def test_ciclo_percepcao_alimenta_proximo_prompt(self):
        orig = _snap([], "Loja")
        try:
            st = statemod.init("achar o campo de busca")
            ctx: dict = {"hist_labels": [], "task_state": st}
            script = _Script([
                PlannerDecision(type="perceive", perception="uia_refresh"),
                PlannerDecision(type="type_text", text="x"),
            ])
            dec, _ = loop.decide("achar", 0, ctx, CFG, planner=script, vocaela=_NoVision())
            self.assertEqual(dec.kind, "perception")
            # run(): executa a releitura e devolve os fatos ao prompt.
            tm: dict = {}
            facts = loop._run_perception(
                dec.perception, ctx, CFG, tm,
                snapshot_fn=lambda: (
                    [{"id": 1, "name": "Pesquisar", "type": "Edit", "bounds": [1, 1, 9, 9]}],
                    "Loja", None,
                ),
            )
            ctx["hist_labels"].append(f"perceive(uia_refresh) => {facts[:160]}")
            ctx["last_result"] = facts[:600]
            dec2, _ = loop.decide("achar", 1, ctx, CFG, planner=script, vocaela=_NoVision())
            self.assertEqual(dec2.action.type, "type")
            self.assertIn("Pesquisar", script.seen[1].get("last_result", ""))
        finally:
            loop.active_window_snapshot = orig

    def test_execute_nunca_toca_hardware_em_pergunta_ou_percepcao(self):
        import actions

        with self.assertRaises(ValueError):
            actions._execute_inner(
                Action(type="perceive", text="uia_refresh"), None, None
            )
        with self.assertRaises(ValueError):
            actions._execute_inner(Action(type="ask", text="q?"), None, None)
        msg = actions.check_preconditions(Action(type="perceive", text="uia_refresh"))
        self.assertIn("kind", msg)


class TestPlannerContract(unittest.TestCase):
    def test_perceive_no_contrato_json_e_spec(self):
        import planner

        self.assertIn("perceive", list(planner.PlannerActionType.__args__))
        self.assertIn("perception", planner.planner_json_schema()["properties"])
        self.assertIn("perceive", planner.TOOLS_SPEC)
        self.assertIn("uia_refresh", planner.TOOLS_SPEC)
        dec = PlannerDecision.model_validate({"type": "perceive", "perception": "uia_refresh"})
        self.assertEqual(dec.perception, "uia_refresh")

    def test_probe_key_perceive(self):
        from evals.probes import decision_key

        self.assertEqual(
            decision_key(PlannerDecision(type="perceive", perception="uia_refresh")),
            "perceive:uia_refresh",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
