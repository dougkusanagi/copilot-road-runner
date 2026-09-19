"""obs/actions/tools offline: multi-monitor, Unicode no type, whitelist.

Roda com: uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import obs  # noqa: E402


class TestCropVirtualDesktop(unittest.TestCase):
    """Desktop virtual 3840x1080 com monitor secundário à ESQUERDA (x=-1920)."""

    FULL = Image.new("RGB", (3840, 1080), "white")
    VORIGIN = (-1920, 0)

    def test_janela_no_monitor_negativo(self):
        # janela em x=-1800..-800 (monitor da esquerda) -> crop nos pixels 120..1120
        crop, origin, full = obs.crop_to_rect(self.FULL, self.VORIGIN,
                                              (-1800, 100, -800, 600))
        self.assertEqual(crop.size, (1000, 500))
        self.assertEqual(origin, (-1800, 100))  # coords de tela, negativas
        self.assertEqual(full, (3840, 1080))

    def test_janela_no_primario(self):
        crop, origin, _ = obs.crop_to_rect(self.FULL, self.VORIGIN,
                                           (100, 100, 700, 500))
        self.assertEqual(crop.size, (600, 400))
        self.assertEqual(origin, (100, 100))

    def test_janela_parcialmente_fora_e_clamp(self):
        crop, origin, _ = obs.crop_to_rect(self.FULL, self.VORIGIN,
                                           (-2000, -50, -1500, 300))
        self.assertEqual(crop.size, (420, 300))  # cortado em x=-1920,y=0
        self.assertEqual(origin, (-1920, 0))

    def test_sem_rect_ou_minusculo_devolve_tudo(self):
        for rect in (None, (0, 0, 20, 20)):
            crop, origin, _ = obs.crop_to_rect(self.FULL, self.VORIGIN, rect)
            self.assertEqual(crop.size, (3840, 1080))
            self.assertEqual(origin, (-1920, 0))

    def test_roundtrip_com_visual_to_action(self):
        # Vocaela devolve 0.5,0.5 no crop -> pixel físico no monitor negativo
        from vocaela import VisualAction, visual_to_action

        crop, origin, _ = obs.crop_to_rect(self.FULL, self.VORIGIN,
                                           (-1800, 100, -800, 600))
        act = visual_to_action(VisualAction(type="click", x=0.5, y=0.5),
                               crop.size, origin)
        self.assertEqual((act.x, act.y), (-1300, 350))


if __name__ == "__main__":
    unittest.main(verbosity=2)
