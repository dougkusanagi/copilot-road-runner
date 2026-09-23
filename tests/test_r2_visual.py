"""R2 (fatia 3): OCR local opcional + confirmação específica com UIA.

Offline, sem GUI/modelos (captura e OCR injetados). Cobre:
- `ocr.py`: backend honesto (winrt/tesseract/unavailable), `read()` nunca
  inventa texto ( indisponível/falha = ok False + motivo);
- `perceive(ocr)`: releitura sem input físico, fato (não evidência),
  indisponibilidade como fato honesto;
- `confirm_effect` com UIA antes/depois: modal dispensado, conteúdo
  visível/novo — título sozinho continua sem confirmar (plano §4.2–§4.3).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loop  # noqa: E402
import ocr as ocrmod  # noqa: E402
import state as statemod  # noqa: E402
import verification as verif  # noqa: E402
from planner import PlannerDecision  # noqa: E402

CFG = {"screenshot_max_width": 1024}


class _Script:
    def __init__(self, decisions: list[PlannerDecision]):
        self._decisions = list(decisions)

    def next_action(self, **kwargs):
        return self._decisions.pop(0), 1.0


class _NoVision:
    def act_sync(self, img, instruction, history=None):
        raise AssertionError("sem visão neste teste")


def _img():
    from PIL import Image

    return Image.new("RGB", (16, 10), (255, 255, 255))


class TestOcrBackend(unittest.TestCase):
    def test_backend_conhecido_e_consistente(self):
        b = ocrmod.backend()
        self.assertIn(b, ("winrt", "tesseract", "unavailable"))
        self.assertEqual(ocrmod.available(), b != "unavailable")
        st = ocrmod.status()
        self.assertEqual(st["backend"], b)
        self.assertEqual(st["available"], b != "unavailable")
        if b == "unavailable":
            self.assertTrue(st["reason"])

    def test_read_indisponivel_nao_levanta_nem_inventa(self):
        orig = ocrmod.backend
        ocrmod.backend = lambda: "unavailable"
        try:
            res = ocrmod.read(_img())
        finally:
            ocrmod.backend = orig
        self.assertFalse(res["ok"])
        self.assertEqual(res["text"], "")
        self.assertTrue(res["reason"])

    def test_read_ok_e_falha_via_backend_falso(self):
        orig_b, orig_t = ocrmod.backend, ocrmod._read_tesseract
        try:
            ocrmod.backend = lambda: "tesseract"
            ocrmod._read_tesseract = lambda png, lang: "  R$  12.499\n"
            res = ocrmod.read(_img())
            self.assertTrue(res["ok"])
            self.assertEqual(res["text"], "R$ 12.499")
            self.assertEqual(res["backend"], "tesseract")

            def _boom(png, lang):
                raise RuntimeError("binário quebrou")

            ocrmod._read_tesseract = _boom
            res2 = ocrmod.read(_img())
            self.assertFalse(res2["ok"])
            self.assertEqual(res2["text"], "")
            self.assertIn("falhou", res2["reason"])
        finally:
            ocrmod.backend = orig_b
            ocrmod._read_tesseract = orig_t

    def test_read_imagem_invalida_vira_motivo(self):
        orig = ocrmod.backend
        ocrmod.backend = lambda: "tesseract"
        try:
            res = ocrmod.read(object())
        finally:
            ocrmod.backend = orig
        self.assertFalse(res["ok"])
        self.assertTrue(res["reason"])


class TestPerceiveOcr(unittest.TestCase):
    def test_parse_aceita_ocr_e_recusa_variantes(self):
        self.assertEqual(loop._parse_perception("ocr"), ("ocr", ""))
        self.assertEqual(loop._parse_perception(" OCR "), ("ocr", ""))
        with self.assertRaises(RuntimeError):
            loop._parse_perception("ocr_total")
        with self.assertRaises(RuntimeError):
            loop._parse_perception("expand:   ")

    def test_ocr_devolve_fatos_sem_input_nem_evidencia(self):
        import actions

        called: list = []
        orig_exec = actions._execute_inner
        actions._execute_inner = lambda *a, **k: (called.append(1), "x")[1]
        try:
            ctx: dict = {"task_state": statemod.init("ler preço")}
            tm: dict = {}
            facts = loop._run_perception(
                "ocr", ctx, {}, tm,
                capture_fn=lambda: (_img(), (0, 0), (16, 10)),
                ocr_fn=lambda img: {"ok": True, "text": "R$ 12.499",
                                    "backend": "tesseract", "ms": 3.0, "reason": ""},
            )
        finally:
            actions._execute_inner = orig_exec
        self.assertIn("ocr", facts)
        self.assertIn("12.499", facts)
        self.assertEqual(called, [])
        self.assertEqual(ctx["task_state"].evidences, [])
        self.assertEqual(tm["perception"]["spec"], "ocr")

    def test_ocr_indisponivel_vira_fato_honesto(self):
        ctx: dict = {"task_state": statemod.init("g")}
        tm: dict = {}
        facts = loop._run_perception(
            "ocr", ctx, {}, tm,
            capture_fn=lambda: (_img(), (0, 0), (16, 10)),
            ocr_fn=lambda img: {"ok": False, "text": "", "backend": "unavailable",
                                "reason": "sem backend OCR", "ms": 0.0},
        )
        self.assertIn("indisponível", facts)
        self.assertEqual(tm["perception"]["spec"], "ocr")
        self.assertEqual(ctx["task_state"].evidences, [])

    def test_decide_ocr_normaliza(self):
        orig = loop.active_window_snapshot
        loop.active_window_snapshot = lambda: ([], "Loja", None)
        try:
            dec, _ = loop.decide(
                "ler", 0, {"hist_labels": []}, CFG,
                planner=_Script([PlannerDecision(type="perceive", perception="ocr")]),
                vocaela=_NoVision(),
            )
        finally:
            loop.active_window_snapshot = orig
        self.assertEqual((dec.kind, dec.perception), ("perception", "ocr"))


class TestConfirmWithUia(unittest.TestCase):
    def test_titulo_sozinho_continua_sem_confirmar(self):
        for at in ("click", "scroll", "open", "focus"):
            ok, _ = verif.confirm_effect(at, "", "A", "B")
            self.assertFalse(ok, at)

    def test_modal_dispensado_confirma(self):
        before = ["Button:Continue shopping", "Window:Loja"]
        after = ["Edit:Pesquisar", "Window:Loja"]
        self.assertTrue(verif.has_modal_indicators(before))
        self.assertFalse(verif.has_modal_indicators(after))
        self.assertTrue(verif.modal_dismissed(before, after))
        ok, note = verif.confirm_effect("click", "", "Loja", "Loja",
                                        ui_before=before, ui_after=after)
        self.assertTrue(ok)
        self.assertIn("dispensado", note)

    def test_modal_sem_listas_e_inconclusivo(self):
        self.assertFalse(verif.modal_dismissed(None, []))
        self.assertFalse(verif.modal_dismissed(["Button:Continue"], None))
        ok, _ = verif.confirm_effect("click", "", "A", "B")
        self.assertFalse(ok)
        ok, _ = verif.confirm_effect(
            "click", "", "A", "B",
            ui_before=["Button:Ok"], ui_after=["Button:Ok"])
        self.assertFalse(ok)

    def test_conteudo_esperado_visivel_confirma(self):
        ok, _ = verif.confirm_effect(
            "click", "R$ 12.499", "Loja", "Loja",
            ui_before=["Edit:Pesquisar"], ui_after=['Text:Preço="R$ 12.499"'])
        self.assertTrue(ok)
        ok, _ = verif.confirm_effect(
            "click", "R$ 12.499", "Loja", "Loja",
            ui_before=["Edit:Pesquisar"], ui_after=["Edit:Pesquisar"])
        self.assertFalse(ok)

    def test_scroll_com_conteudo_novo_confirma(self):
        ok, _ = verif.confirm_effect(
            "scroll", "", "A", "A",
            ui_before=["Text:Item 1"], ui_after=["Text:Item 1", "Text:Item 2"])
        self.assertTrue(ok)
        ok, _ = verif.confirm_effect(
            "scroll", "", "A", "A",
            ui_before=["Text:Item 1"], ui_after=["Text:Item 1"])
        self.assertFalse(ok)


class TestVerifyDryRun(unittest.TestCase):
    def test_dry_run_devolve_tupla_com_ui_vazia(self):
        from schemas import Action as _A

        ok, note, ui = loop.verify(_A(type="wait", ms=10), "g", {}, dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(ui, [])
        self.assertIn("dry_run", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
