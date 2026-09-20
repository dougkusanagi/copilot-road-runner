"""R2 (fatia 1): observação diagnosticável e alvos válidos.

Offline, sem GUI/modelos (UIA mockada onde o provider é imprevisível).
Cobre: diagnóstico UIA (vazio vs timeout vs truncado vs erro), recusa de
alvo ambíguo, FrameRef/DPI + guarda de frame obsoleto, anti-loop com
resultado, fixtures sanitizadas (UIA vazia, modal) e confirmação nunca só
por título (plano §4.2–§4.3).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loop  # noqa: E402
import obs as obsmod  # noqa: E402
import state as statemod  # noqa: E402
import uia as uiamod  # noqa: E402
import verification as verif  # noqa: E402
from planner import PlannerDecision  # noqa: E402
from schemas import Decision  # noqa: E402

CFG = {"screenshot_max_width": 1024}


class _Script:
    def __init__(self, decisions: list[PlannerDecision]):
        self._decisions = list(decisions)

    def next_action(self, **kwargs):
        return self._decisions.pop(0), 1.0


class _NoVision:
    def act_sync(self, img, instruction, history=None):
        raise AssertionError("sem visão neste teste")


class TestUiaDiag(unittest.TestCase):
    def test_diag_text_distinguishes_cases(self):
        self.assertIn("lista completa", uiamod._diag_text({"status": "ok", "count": 3,
                                                           "max_elements": 120, "elapsed_ms": 5}))
        self.assertIn("PROVIDER VAZIO", uiamod._diag_text({"status": "provider_empty",
                                                           "count": 0, "max_elements": 120,
                                                           "elapsed_ms": 5}))
        self.assertIn("TRUNCADO", uiamod._diag_text({"status": "truncated", "count": 120,
                                                    "max_elements": 120, "elapsed_ms": 5}))
        self.assertIn("TIMEOUT", uiamod._diag_text({"status": "timeout_partial", "count": 4,
                                                   "max_elements": 120, "elapsed_ms": 5000}))
        self.assertIn("sem janela", uiamod._diag_text({"status": "no_window", "count": 0,
                                                      "max_elements": 120, "elapsed_ms": 1}))
        self.assertIn("ERRO", uiamod._diag_text({"status": "error", "error": "boom",
                                                "count": 0, "max_elements": 120,
                                                "elapsed_ms": 1}))

    def test_snapshot_maps_diag_to_error(self):
        orig_fn = uiamod.active_window_snapshot
        orig_diag = dict(uiamod.LAST_DIAG)
        try:
            uiamod.active_window_snapshot = lambda **k: ([], "Win", None)
            uiamod._set_diag(status="provider_empty", count=0, max_elements=120,
                             elapsed_ms=2.0)
            ob = uiamod.snapshot()
            self.assertEqual(ob.error, "provider_empty")
            self.assertIn("PROVIDER VAZIO", ob.coverage)
            self.assertFalse(ob.truncated)
            items = [{"id": 0, "name": "A", "type": "Button", "bounds": [1, 1, 9, 9]}]
            uiamod.active_window_snapshot = lambda **k: (items, "Win", None)
            uiamod._set_diag(status="ok", count=1, max_elements=120, elapsed_ms=2.0)
            ob2 = uiamod.snapshot()
            self.assertEqual(ob2.error, "")
        finally:
            uiamod.active_window_snapshot = orig_fn
            uiamod._set_diag(**orig_diag)

    def test_loop_records_uia_diag(self):
        orig = loop.active_window_snapshot
        loop.active_window_snapshot = lambda: ([], "Edge", None)
        try:
            _, tm = loop.decide(
                "g", 0, {"hist_labels": []}, CFG,
                planner=_Script([PlannerDecision(type="wait", ms=10)]),
                vocaela=_NoVision(),
            )
        finally:
            loop.active_window_snapshot = orig
        self.assertIn("uia_diag", tm)


class TestAmbiguity(unittest.TestCase):
    ITEMS = [
        {"id": 0, "name": "Salvar", "type": "Button", "bounds": [10, 10, 60, 30],
         "context": "Barra"},
        {"id": 1, "name": "Salvar", "type": "MenuItem", "bounds": [100, 100, 160, 130],
         "context": "Menu"},
    ]

    def test_ambiguo_recusado_com_contexto(self):
        act, note = loop._resolve_uia(self.ITEMS, "Salvar", None)
        self.assertIsNone(act)
        self.assertTrue(note.startswith("alvo ambíguo"))
        self.assertIn("Barra", note)
        self.assertIn("Menu", note)

    def test_duplicado_mesmo_ponto_clica(self):
        dups = [dict(self.ITEMS[0]), dict(self.ITEMS[0])]
        dups[1]["id"] = 9
        act, note = loop._resolve_uia(dups, "Salvar", None)
        self.assertIsNotNone(act)
        self.assertEqual(note, "")

    def test_unico_passsa(self):
        act, note = loop._resolve_uia(self.ITEMS[:1], "Salvar", None)
        self.assertIsNotNone(act)
        self.assertEqual((act.x, act.y), (35, 20))

    def test_uia_click_ambiguo_vira_erro_ao_modelo(self):
        orig = loop.active_window_snapshot
        loop.active_window_snapshot = lambda: (self.ITEMS, "App", None)
        try:
            with self.assertRaises(RuntimeError) as cm:
                loop.decide(
                    "salve o arquivo", 1, {"hist_labels": []}, CFG,
                    planner=_Script([PlannerDecision(type="uia_click", target="Salvar")]),
                    vocaela=_NoVision(),
                )
        finally:
            loop.active_window_snapshot = orig
        self.assertIn("ambíguo", str(cm.exception))


class TestFrameStale(unittest.TestCase):
    def test_frame_ref_ids_unicos_e_dpi(self):
        f1 = obsmod.frame_ref_for((0, 0), (800, 600), "A", "obs-1")
        f2 = obsmod.frame_ref_for((-1920, 0), (800, 600), "A", "obs-1")
        self.assertNotEqual(f1.frame_id, f2.frame_id)
        self.assertEqual(f2.origin, [-1920, 0])
        self.assertGreaterEqual(f1.scale_dpi, 1.0)
        self.assertEqual(f1.observation_id, "obs-1")
        f1.captured_at -= 3600
        self.assertTrue(obsmod.frame_is_stale(f1, max_age_s=5))

    def test_imagem_alterada_muda_referencia(self):
        ctx: dict = {"task_state": statemod.init("g")}
        tm1: dict = {}
        tm2: dict = {}
        loop._run_perception("uia_refresh", ctx, {}, tm1,
                             snapshot_fn=lambda: ([], "A", None))
        loop._run_perception("uia_refresh", ctx, {}, tm2,
                             snapshot_fn=lambda: ([], "B", None))
        self.assertNotEqual(tm1["perception"]["observation_id"],
                            tm2["perception"]["observation_id"])

    def test_visual_stale_note(self):
        from schemas import Action as _A

        dec = Decision(action=_A(type="click", x=1, y=1), source="vocaela")
        self.assertEqual(loop._visual_stale_note(dec, {}), "")
        dec2 = Decision(action=_A(type="click", x=1, y=1), source="planner")
        self.assertEqual(loop._visual_stale_note(dec2, {"visual_title": "A"}), "")
        orig = loop._foreground_title
        try:
            loop._foreground_title = lambda: "A"
            self.assertEqual(
                loop._visual_stale_note(dec, {"visual_title": "A"}), "")
            loop._foreground_title = lambda: "Modal - A"
            msg = loop._visual_stale_note(dec, {"visual_title": "A"})
            self.assertIn("obsoleto", msg)
            self.assertIn("Modal", msg)
        finally:
            loop._foreground_title = orig


class TestAntiLoopResult(unittest.TestCase):
    def test_mesmo_resultado_sem_mudanca_sem_progresso(self):
        fp = loop._state_fingerprint("A", ["Button:X"])
        h = [["k", fp, "w|no visible effect"]] * 3
        self.assertFalse(loop._loop_has_progress(h[0], h[1], h[2]))

    def test_resultado_diferente_e_progresso(self):
        fp = loop._state_fingerprint("A", ["Button:X"])
        self.assertTrue(loop._loop_has_progress(
            ["k", fp, "w|erro 1"], ["k", fp, "w|erro 2"], ["k", fp, ""]))
        self.assertTrue(loop._loop_has_progress(
            ["k", "fp1", "w|x"], ["k", "fp2", "w|x"], ["k", "fp3", ""]))

    def test_resultado_desconhecido_mantem_regra_antiga(self):
        fp = loop._state_fingerprint("A", ["Button:X"])
        h = [["k", fp, ""]] * 3
        self.assertFalse(loop._loop_has_progress(h[0], h[1], h[2]))


class TestTitleNeverConfirms(unittest.TestCase):
    def test_titulo_sozinho_nao_confirma_nada(self):
        ok, _ = verif.confirm_effect("type", "Olá", "A", "B", "")
        self.assertFalse(ok)
        ok, _ = verif.confirm_effect("open", "", "A", "B")
        self.assertFalse(ok)
        ok, _ = verif.confirm_effect("click", "", "A", "B")
        self.assertFalse(ok)
        ok, _ = verif.confirm_effect("scroll", "", "A", "B")
        self.assertFalse(ok)

    def test_done_exige_ref_exata_mesmo_com_titulo_igual(self):
        ok, _ = verif.done_evidence_ok(["window 'A'"], ["outra evidência"], [])
        self.assertFalse(ok)


class TestR2Fixtures(unittest.TestCase):
    def test_uia_vazia(self):
        from evals.probes import check_decision, load_fixture

        fx = load_fixture("uia-vazia")
        bad = check_decision(fx, PlannerDecision(type="hotkey", keys="ctrl+t"))
        self.assertFalse(bad["pass"])
        self.assertTrue(check_decision(
            fx, PlannerDecision(type="visual_action", instruction="Click Box"))["pass"])
        self.assertTrue(check_decision(
            fx, PlannerDecision(type="perceive", perception="uia_refresh"))["pass"])

    def test_modal(self):
        from evals.probes import check_decision, load_fixture

        fx = load_fixture("modal-dialog")
        self.assertTrue(check_decision(
            fx, PlannerDecision(type="uia_click", target="Não salvar"))["pass"])
        bad = check_decision(fx, PlannerDecision(type="type_text", text="x"))
        self.assertFalse(bad["pass"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
