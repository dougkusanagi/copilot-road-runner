"""Tray/Spotlight/ditado: lógica pura, sem mic, modelo, webview ou pystray.

Roda com: uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as appmod  # noqa: E402
import stt  # noqa: E402


class _FakeEngine:
    """Devolve texto proporcional ao áudio recebido (simula parcial crescendo)."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, samples: array) -> str:
        self.calls += 1
        n = len(samples) // 1600  # 1 palavra a cada 100 ms
        return " ".join(["palavra"] * n).strip()


def _voice(ms: int) -> array:
    return array("f", [0.2, -0.2] * (16 * ms // 2))  # rms 0.2 > limiar


def _silence(ms: int) -> array:
    return array("f", [0.0] * (16 * ms))


class TestDictation(unittest.TestCase):
    def setUp(self):
        self.engine = _FakeEngine()
        self.partials: list[str] = []
        self.finals: list[tuple[str, bool]] = []
        self.d = stt.Dictation(self.engine, self.partials.append,
                               lambda t, s: self.finals.append((t, s)),
                               partial_every_ms=1000, silence_ms=1500,
                               silence_rms=0.01, auto_send=True)

    def _run(self, blocks, t0=100.0, step=0.1):
        now = t0
        self.d.start(now)
        for b in blocks:
            now += step
            self.d.feed(b, now)
        return now

    def test_parciais_no_intervalo_e_final_por_silencio_envia(self):
        blocks = [_voice(100)] * 25 + [_silence(100)] * 16  # 2.5 s fala + 1.6 s silêncio
        self._run(blocks)
        self.assertGreaterEqual(len(self.partials), 2)  # ~1 por segundo de fala
        self.assertTrue(all(p for p in self.partials))
        self.assertEqual(len(self.finals), 1)
        text, sent = self.finals[0]
        self.assertTrue(text.startswith("palavra"))
        self.assertTrue(sent)  # auto_send
        self.assertFalse(self.d.active)

    def test_sem_voz_nao_emite_nada(self):
        self._run([_silence(100)] * 40)
        self.assertEqual(self.partials, [])
        self.assertEqual(self.finals, [])  # silêncio sem fala prévia não finaliza
        self.assertTrue(self.d.active)

    def test_stop_sem_enviar_mantem_texto(self):
        self._run([_voice(100)] * 12)
        text = self.d.stop(send=False)
        self.assertTrue(text)
        self.assertEqual(self.finals, [(text, False)])
        self.assertEqual(self.d.stop(send=True), text)  # idempotente
        self.assertEqual(len(self.finals), 1)

    def test_stop_enviar(self):
        self._run([_voice(100)] * 12)
        self.d.stop(send=True)
        self.assertEqual(self.finals[0][1], True)

    def test_auto_send_false_nunca_envia(self):
        self.d.auto_send = False
        self._run([_voice(100)] * 15 + [_silence(100)] * 16)
        self.assertEqual(len(self.finals), 1)
        self.assertFalse(self.finals[0][1])

    def test_engine_com_erro_nao_derruba_nem_envia(self):
        class Boom:
            def transcribe(self, s):
                raise RuntimeError("modelo ausente")
        errors: list[str] = []
        d = stt.Dictation(Boom(), self.partials.append,
                          lambda t, s: self.finals.append((t, s)),
                          on_error=errors.append,
                          partial_every_ms=500, silence_ms=1000, auto_send=True)
        now = 0.0
        d.start(now)
        for _ in range(12):
            now += 0.1
            d.feed(_voice(100), now)
        for _ in range(12):
            now += 0.1
            d.feed(_silence(100), now)
        self.assertEqual(self.partials, [])  # erro nunca vira texto
        self.assertTrue(errors and errors[0].startswith("stt: RuntimeError"))
        self.assertEqual(self.finals, [("", False)])  # e nunca envia

    def test_buffer_limitado(self):
        d = stt.Dictation(self.engine, lambda t: None, lambda t, s: None,
                          max_utterance_s=1, partial_every_ms=10_000)
        d.start(0.0)
        for i in range(30):
            d.feed(_voice(100), i * 0.1)
        self.assertEqual(len(d._buf), 16000)

    def test_rms_e_builders(self):
        self.assertAlmostEqual(stt.rms(array("f", [0.5, -0.5])), 0.5)
        self.assertEqual(stt.rms(array("f")), 0.0)
        import config as cfgmod

        cfg = cfgmod.load("nao-existe.json")
        eng = stt.build_engine(cfg)
        self.assertEqual((eng.model_name, eng.compute_type, eng.language),
                         ("base", "int8", "pt"))
        d = stt.build_dictation(cfg, self.engine, lambda t: None, lambda t, s: None)
        self.assertEqual(d.silence, 1.5)
        self.assertTrue(d.auto_send)
        with self.assertRaises(ValueError):
            stt.build_engine({"stt": {"engine": "x"}})


class TestAppPuro(unittest.TestCase):
    def test_js_call_serializa_json(self):
        self.assertEqual(appmod.js_call("partial", 'Olá "x"'),
                         'window.crr.partial("Olá \\"x\\"")')
        self.assertEqual(appmod.js_call("final", "t", True), 'window.crr.final("t", true)')
        self.assertEqual(appmod.js_call("focus"), "window.crr.focus()")

    def test_line_tee_quebra_linhas_e_ecoa(self):
        import io

        real = io.StringIO()
        lines: list[str] = []
        tee = appmod.LineTee(real, lines.append)
        print("a", file=tee)
        tee.write("b\nc")
        tee.write("\n\n")
        self.assertEqual(lines, ["a", "b", "c"])
        self.assertEqual(real.getvalue(), "a\nb\nc\n\n")

    def test_classify(self):
        self.assertEqual(appmod.classify("PARADO step 2: decisao falhou"), "err")
        self.assertEqual(appmod.classify("[3] VERIFY active='Notepad'"), "ok")
        self.assertEqual(appmod.classify("[1] PLANNER open(\"notepad\")"), "")

    def test_jsapi_encaminha_para_app(self):
        calls: list = []

        class FakeApp:
            hotkey = "ctrl+alt+space"

            def js(self, *a):
                calls.append(("js", a))

            def run_task(self, t):
                calls.append(("run", t))

            def dictation_start(self):
                calls.append(("dstart",))

            def dictation_stop(self, send):
                calls.append(("dstop", send))

            def hide(self):
                calls.append(("hide",))

        api = appmod.JsApi(FakeApp())
        api.ready()
        api.submit("  abra o notepad ")
        api.submit("")
        api.dictation_start()
        api.dictation_stop(True)
        api.hide()
        self.assertEqual(calls, [("js", ("hotkey", "ctrl+alt+space")),
                                 ("run", "abra o notepad"), ("run", ""),
                                 ("dstart",), ("dstop", True), ("hide",)])

    def test_app_config_e_run_task_vazio(self):
        import config as cfgmod

        a = appmod.App(cfgmod.load("nao-existe.json"))
        self.assertEqual(a.hotkey, "ctrl+alt+space")
        self.assertEqual(a.width, 720)
        a.run_task("")  # sem janela e sem texto: no-op
        self.assertFalse(a.running)

    def test_html_existe_e_usa_api(self):
        html = appmod.UI_HTML.read_text(encoding="utf-8")
        for needle in ("pywebview.api", "window.crr", "dictation_start",
                       "dictation_stop", "submit(", "id=\"mic\"", "id=\"stop\"",
                       "id=\"send\"", "abort()", "pywebviewready"):
            self.assertIn(needle, html, f"index.html sem: {needle}")
        for fn in ("partial", "final", "running", "step", "done", "error",
                   "hotkey", "focus"):
            self.assertIn(f"{fn}(", html, f"window.crr.{fn} ausente")

    def test_pyproject_extra_ui_e_cli(self):
        import subprocess

        py = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for dep in ("pywebview", "pystray", "faster-whisper", "sounddevice"):
            self.assertIn(dep, py)
        out = subprocess.run([sys.executable, "main.py", "--help"],
                             capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertIn("--ui", out.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
