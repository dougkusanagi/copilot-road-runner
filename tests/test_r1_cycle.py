"""R1: ciclo observação→decisão→resultado→próximo prompt (plano §4.1/§7).

Offline, sem GUI/modelos (snapshot mockado, planners fake). Cobre o
critério de saída de R1: o teste atravessa o ciclo real, impede falso
done e impede duplicação sem evidência; IDs de observação nunca se repetem.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loop  # noqa: E402
import state as statemod  # noqa: E402
import verification as verif  # noqa: E402
from planner import PlannerDecision  # noqa: E402
from schemas import Action, ActionResult, Decision  # noqa: E402

CFG = {"screenshot_max_width": 1024}


class _Script:
    """Planner fake com decisões programadas; registra o prompt recebido."""

    def __init__(self, decisions: list[PlannerDecision]):
        self._decisions = list(decisions)
        self.seen: list[dict] = []

    def next_action(self, **kwargs):
        self.seen.append(dict(kwargs))
        dec = self._decisions.pop(0)
        return dec, 1.0


class _NoVision:
    def act_sync(self, img, instruction, history=None):
        raise AssertionError("sem visão neste ciclo")


def _snap(items, title, wrect=(0, 0, 800, 600)):
    orig = loop.active_window_snapshot
    loop.active_window_snapshot = lambda: (items, title, wrect)
    return orig


class TestR1Cycle(unittest.TestCase):
    def test_obs_nao_vira_evidencia_sozinha(self):
        orig = _snap([], "Bloco de Notas", None)
        try:
            ctx: dict = {"hist_labels": [], "task_state": statemod.init("digitar oi")}
            dec, tm = loop.decide(
                "digitar oi",
                0,
                ctx,
                CFG,
                planner=_Script([PlannerDecision(type="type_text", text="oi")]),
                vocaela=_NoVision(),
            )
        finally:
            loop.active_window_snapshot = orig
        self.assertEqual(dec.action.type, "type")
        # R1: observar não confirma — nada da observação entra em evidences.
        st = ctx["task_state"]
        self.assertEqual(st.evidences, [])
        self.assertIn("observation_id", tm)
        self.assertEqual(dec.observation_ref, tm["observation_id"])
        self.assertIn(tm["observation_id"], ctx.get("last_observation", ""))

    def test_ids_de_observacao_nunca_reutilizados(self):
        orig = _snap([], "Edge", None)
        try:
            ctx: dict = {"hist_labels": [], "task_state": statemod.init("g")}
            _, tm1 = loop.decide(
                "g", 0, ctx, CFG,
                planner=_Script([PlannerDecision(type="wait", ms=10)]),
                vocaela=_NoVision(),
            )
            _, tm2 = loop.decide(
                "g", 1, ctx, CFG,
                planner=_Script([PlannerDecision(type="wait", ms=10)]),
                vocaela=_NoVision(),
            )
        finally:
            loop.active_window_snapshot = orig
        self.assertNotEqual(tm1["observation_id"], tm2["observation_id"])

    def test_ciclo_completo_e_falso_done_vetado(self):
        items = [{"id": 0, "name": "Buscar", "type": "Button", "bounds": [10, 10, 60, 30]}]
        orig = _snap(items, "Loja", None)
        try:
            st = statemod.init("pesquisar o produto e reportar")
            ctx: dict = {"hist_labels": [], "task_state": st}
            # Passo 1: modelo digita a busca.
            script1 = _Script([PlannerDecision(type="type_text", text="rtx")])
            dec1, tm1 = loop.decide("pesquisar", 0, ctx, CFG, planner=script1, vocaela=_NoVision())
            self.assertEqual(dec1.action.type, "type")
            # run(): confirmação específica do efeito antes de memorizar.
            label = "type(rtx)"
            vnote = "window 'Loja' => text visible in focused field"
            ok, _ = verif.confirm_effect("type", "rtx", "Loja", vnote, vnote)
            self.assertTrue(ok)
            confirmed_label = f"{label} => {vnote}"
            statemod.add_evidence(st, confirmed_label)
            ctx["hist_labels"].append(confirmed_label)
            ctx["last_result"] = confirmed_label
            # Passo 2: próximo prompt carrega memória + último resultado.
            script2 = _Script([PlannerDecision(type="done", evidences=[confirmed_label])])
            dec2, _ = loop.decide("pesquisar", 1, ctx, CFG, planner=script2, vocaela=_NoVision())
            self.assertEqual(dec2.action.type, "done")
            got = script2.seen[0]
            self.assertIn("evidências confirmadas", got.get("task_summary", ""))
            self.assertIn(confirmed_label[:40], got.get("task_summary", ""))
            self.assertIn(label, got.get("last_result", ""))
            # Falso done: ação enviada não prova objetivo — refs fora da
            # memória são vetadas mesmo com histórico de ações no contexto.
            with self.assertRaises(RuntimeError):
                loop.decide(
                    "pesquisar", 2, ctx, CFG,
                    planner=_Script([PlannerDecision(type="done", evidences=["fantasma"])]),
                    vocaela=_NoVision(),
                )
        finally:
            loop.active_window_snapshot = orig

    def test_concluida_sem_evidencia_e_ignorada(self):
        st = statemod.init("g")
        statemod.apply_update(st, {"done_items": ["aba aberta"], "subgoal": "navegar"})
        self.assertNotIn("aba aberta", st.done_items)  # sem refs: ignorada
        self.assertEqual(st.subgoal, "navegar")  # resto da proposta vale
        ev = "hotkey(ctrl+t) => nova aba observada"
        statemod.add_evidence(st, ev)
        statemod.apply_update(
            st, {"done_items": ["aba aberta"], "evidence_refs": [ev]}
        )
        self.assertIn("aba aberta", st.done_items)
        # Ref desconhecida também não aceita.
        statemod.apply_update(
            st, {"done_items": ["loja aberta"], "evidence_refs": ["obs-fantasma"]}
        )
        self.assertNotIn("loja aberta", st.done_items)

    def test_proposta_vs_aceita_registrada(self):
        orig = _snap([], "Edge", None)
        try:
            ctx: dict = {"hist_labels": [], "task_state": statemod.init("g")}
            dec = PlannerDecision(
                type="wait",
                ms=10,
                task_update={"done_items": ["x"], "subgoal": "s"},
            )
            _, tm = loop.decide("g", 0, ctx, CFG, planner=_Script([dec]), vocaela=_NoVision())
        finally:
            loop.active_window_snapshot = orig
        self.assertEqual(tm.get("task_update_proposed", {}).get("subgoal"), "s")
        self.assertEqual(tm.get("task_update_accepted_done"), [])
        self.assertIn("evidence_refs", tm.get("task_update_rejected", ""))

    def test_sequence_discriminada_sem_wait_ficticio(self):
        orig = _snap([], "Nova guia - Google Chrome", None)
        try:
            ctx: dict = {"hist_labels": [], "task_state": statemod.init("navegar")}
            dec, _ = loop.decide(
                "navegar",
                1,
                ctx,
                CFG,
                planner=_Script([
                    PlannerDecision(
                        type="sequence",
                        steps=[
                            {"type": "hotkey", "keys": "ctrl+l"},
                            {"type": "type_text", "text": "https://www.amazon.com"},
                            {"type": "press_key", "key": "enter"},
                        ],
                    )
                ]),
                vocaela=_NoVision(),
            )
        finally:
            loop.active_window_snapshot = orig
        self.assertEqual(dec.kind, "sequence")
        self.assertEqual([a.type for a in (dec.steps or [])], ["hotkey", "type", "hotkey"])
        self.assertNotEqual((dec.action.type, dec.action.ms), ("wait", 0))
        # kind=action nunca contrabandeia steps.
        with self.assertRaises(ValueError):
            Decision(
                action=Action(type="wait", ms=0),
                source="planner",
                steps=[Action(type="hotkey", key="ctrl+l")],
            )

    def test_action_result_sem_envio_nao_confirma(self):
        ar = ActionResult(sent="not_sent", confirmed=False, post_state="dry_run")
        self.assertFalse(ar.confirmed)
        self.assertEqual(ar.sent, "not_sent")
        self.assertEqual(ar.evidences, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
