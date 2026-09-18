"""Testes da arquitetura de 2 modelos (offline + mock HTTP, sem GUI).

- Planner: prompt compacto sem screenshot, JSON tolerante, veto a coordenadas.
- Vocaela: parser do formato oficial <Action>[...]</Action>, normalizaÃ§Ã£o 0..1.
- IntegraÃ§Ã£o: clientes OpenAI-compatible contra servidores mock locais.
- UIA resolve por nome (sem scorer no fluxo principal).

Roda com: .\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import config as cfgmod  # noqa: E402
import planner  # noqa: E402
import vocaela  # noqa: E402


# --- helpers mock ------------------------------------------------------------
class _MockState:
    seen: list[dict] = []
    reply_text: str = ""


def _make_server(reply_text: str):
    seen: list[dict] = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.endswith("/models"):
                body = json.dumps({"data": [{"id": "mock"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            seen.append(json.loads(self.rfile.read(n) or b"{}"))
            body = json.dumps({"choices": [{"message": {"content": reply_text}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


# --- planner -----------------------------------------------------------------
class TestPlannerPrompt(unittest.TestCase):
    def test_compacto_sem_screenshot(self):
        p = planner.build_prompt("Abra o notepad", "Bloco de Notas",
                                 ["Arquivo", "Editar"], ["open_app(notepad)"])
        self.assertIn("Abra o notepad", p)
        self.assertIn("Bloco de Notas", p)
        self.assertIn("Arquivo", p)
        self.assertIn("open_app(notepad)", p)
        for banned in ("base64", "image_url", "data:image"):
            self.assertNotIn(banned, p)

    def test_historico_limitado_a_5(self):
        p = planner.build_prompt("g", "w", ["a"], [f"a{i}" for i in range(10)])
        self.assertNotIn("a0", p.split("Recent actions:")[1])
        self.assertIn("a9", p)

    def test_system_proibe_coordenadas(self):
        sys = planner.PLANNER_SYSTEM
        self.assertIn("NEVER output coordinates", sys)
        self.assertIn("visual_action", sys)
        self.assertIn("uia_click", sys)


class TestPlannerJson(unittest.TestCase):
    def test_limpo(self):
        d = planner.extract_json('{"type": "done"}')
        self.assertEqual(d, {"type": "done"})

    def test_fenced(self):
        d = planner.extract_json('```json\n{"type":"open_app","app":"notepad"}\n```')
        self.assertEqual(d["app"], "notepad")

    def test_ruido(self):
        d = planner.extract_json('Sure! {"type": "wait", "ms": 500} ok')
        self.assertEqual(d["ms"], 500)

    def test_invalido(self):
        with self.assertRaises(ValueError):
            planner.extract_json("olÃ¡, clique ali")

    def test_veta_coords(self):
        dec = planner.PlannerDecision.model_validate({"type": "visual_action",
                                                      "instruction": "Click X"})
        with self.assertRaises(ValueError):
            dec.assert_no_coords({"type": "click", "x": 100, "y": 200})

    def test_decision_valida(self):
        dec = planner.PlannerDecision.model_validate({"type": "type_text",
                                                      "text": "OlÃ¡"})
        self.assertEqual(dec.text, "OlÃ¡")

    def test_tipo_desconhecido_rejeitado(self):
        with self.assertRaises(Exception):
            planner.PlannerDecision.model_validate({"type": "abra_tudo"})


class TestPlannerClient(unittest.TestCase):
    def test_roundtrip_sem_imagem(self):
        srv, seen = _make_server('{"type": "open_app", "app": "notepad"}')
        try:
            base = f"http://127.0.0.1:{srv.server_port}/v1"
            pl = planner.MiniCPMPlanner(base_url=base, model="MiniCPM5-1B")
            self.assertTrue(pl.check()["ok"])
            dec, ms = pl.next_action("goal", "win", ["a"], [])
            self.assertEqual(dec.type, "open_app")
            self.assertEqual(dec.app, "notepad")
            self.assertGreaterEqual(ms, 0)
            payload = seen[0]
            blob = json.dumps(payload)
            self.assertNotIn("image_url", blob)
            self.assertNotIn("base64", blob)
            self.assertIn("MiniCPM5-1B", payload["model"])
            self.assertLessEqual(payload["temperature"], 0.2)
        finally:
            srv.shutdown()


# --- vocaela -----------------------------------------------------------------
class TestVocaelaParse(unittest.TestCase):
    def test_formato_oficial_click(self):
        va = vocaela.parse_vocaela_output(
            '<Action>[{"action": "CLICK", "coordinate": [0.1, 0.5]}]</Action>')
        self.assertEqual((va.type, va.x, va.y), ("click", 0.1, 0.5))

    def test_minusculo_e_multiplas_usa_primeira(self):
        va = vocaela.parse_vocaela_output(
            '<Action>[{"action": "click", "coordinate": [0.2, 0.3]}, '
            '{"action": "type", "text": "oi"}]</Action>')
        self.assertEqual(va.type, "click")

    def test_type(self):
        va = vocaela.parse_vocaela_output(
            '<Action>[{"action": "TYPE", "text": "hello"}]</Action>')
        self.assertEqual((va.type, va.text), ("type", "hello"))

    def test_drag(self):
        va = vocaela.parse_vocaela_output(
            '<Action>[{"action": "DRAG", "coordinate": [0.1, 0.2], '
            '"coordinate2": [0.3, 0.4]}]</Action>')
        self.assertEqual((va.type, va.x2, va.y2), ("drag", 0.3, 0.4))

    def test_scroll_hotkey_presskey(self):
        va = vocaela.parse_vocaela_output(
            '<Action>[{"action": "SCROLL", "scroll_direction": "up"}]</Action>')
        self.assertEqual((va.type, va.scroll_direction), ("scroll", "up"))
        va = vocaela.parse_vocaela_output(
            '<Action>[{"action": "HOTKEY", "hotkeys": ["ctrl", "c"]}]</Action>')
        self.assertEqual((va.type, va.key), ("hotkey", "ctrl+c"))
        va = vocaela.parse_vocaela_output(
            '<Action>[{"action": "PRESS_KEY", "key": "enter"}]</Action>')
        self.assertEqual((va.type, va.key), ("key", "enter"))

    def test_bare_json_sem_tags(self):
        va = vocaela.parse_vocaela_output('{"action": "click", "coordinate": [0.5, 0.5]}')
        self.assertEqual(va.type, "click")

    def test_fora_de_range_rejeita(self):
        with self.assertRaises(ValueError):
            vocaela.parse_vocaela_output(
                '<Action>[{"action": "CLICK", "coordinate": [53, 91]}]</Action>')

    def test_lixo_rejeita(self):
        with self.assertRaises(ValueError):
            vocaela.parse_vocaela_output("nÃ£o achei nada na tela")

    def test_acao_desconhecida_rejeita(self):
        with self.assertRaises(ValueError):
            vocaela.parse_vocaela_output(
                '<Action>[{"action": "TELEPORT", "coordinate": [0.1, 0.1]}]</Action>')


class TestVocaelaAdapter(unittest.TestCase):
    def test_prep_mantem_aspect_e_teto(self):
        img = Image.new("RGB", (1920, 1080), "white")
        b64, (w, h) = vocaela._prep_image(img, max_long_edge=1024)
        self.assertEqual((w, h), (1024, 576))
        self.assertTrue(b64)

    def test_prep_nao_amplia(self):
        img = Image.new("RGB", (800, 600), "white")
        _, (w, h) = vocaela._prep_image(img, max_long_edge=1024)
        self.assertEqual((w, h), (800, 600))

    def test_system_message_oficial_no_request(self):
        reply = '<Action>[{"action": "CLICK", "coordinate": [0.5, 0.25]}]</Action>'
        srv, seen = _make_server(reply)
        try:
            base = f"http://127.0.0.1:{srv.server_port}/v1"
            ad = vocaela.VocaelaAdapter(base_url=base)
            self.assertTrue(ad.check()["ok"])
            va, ms = ad.act_sync(Image.new("RGB", (100, 100), "white"),
                                 "Click the address bar")
            self.assertEqual((va.type, va.x, va.y), ("click", 0.5, 0.25))
            payload = seen[0]
            msgs = payload["messages"]
            self.assertIn("navigate the computer screen", msgs[0]["content"])
            user_blob = json.dumps(msgs[1])
            self.assertIn("image_url", user_blob)
            self.assertIn("Click the address bar", user_blob)
        finally:
            srv.shutdown()

    def test_visual_to_action_com_origin(self):
        va = vocaela.VisualAction(type="click", x=0.5, y=0.5)
        act = vocaela.visual_to_action(va, (1000, 500), (100, 200))
        self.assertEqual((act.x, act.y), (600, 450))


# --- config ------------------------------------------------------------------
class TestConfig(unittest.TestCase):
    def test_defaults_2_modelos(self):
        cfg = cfgmod.load("nao-existe.json")
        self.assertEqual(cfg["planner"]["model"], "MiniCPM5-1B")
        self.assertEqual(cfg["vision"]["model"], "Vocaela-2-500M-1024R2")
        self.assertIn("8091", cfg["planner"]["base_url"])
        self.assertIn("8082", cfg["vision"]["base_url"])
        self.assertEqual(cfg["screenshot_max_width"], 1024)

    def test_migra_legado(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            p.write_text(json.dumps({"base_url": "http://127.0.0.1:1234/v1",
                                     "vision_model": "MAI-UI-2B",
                                     "scorer_threshold": 0.8}), encoding="utf-8")
            cfg = cfgmod.load(p)
            self.assertIn("1234", cfg["planner"]["base_url"])
            self.assertIn("1234", cfg["vision"]["base_url"])
            self.assertNotIn("scorer_threshold", cfg)


# --- UIA resolve --------------------------------------------------------------
class TestResolveUia(unittest.TestCase):
    ITEMS = [
        {"id": 0, "name": "Sete", "type": "Button", "bounds": [10, 10, 50, 50]},
        {"id": 1, "name": "Minimizar Calculadora", "type": "Button",
         "bounds": [10, 10, 50, 50]},
        {"id": 2, "name": "Calculadora", "type": "Window",
         "bounds": [0, 0, 400, 400]},
    ]

    def test_exact(self):
        from loop import _resolve_uia

        a = _resolve_uia(self.ITEMS, "Sete", (0, 0, 400, 400),
                         state_title="Calculadora")
        self.assertIsNotNone(a)
        self.assertEqual((a.x, a.y), (30, 30))

    def test_pula_chrome_e_janela(self):
        from loop import _resolve_uia

        self.assertIsNone(_resolve_uia(self.ITEMS, "Minimizar", (0, 0, 400, 400)))
        self.assertIsNone(_resolve_uia(self.ITEMS, "Calculadora", (0, 0, 400, 400),
                                       state_title="Calculadora"))

    def test_miss_fora_da_janela(self):
        from loop import _resolve_uia

        self.assertIsNone(_resolve_uia(self.ITEMS, "Sete", (500, 500, 900, 900)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
