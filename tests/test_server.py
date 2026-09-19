"""Runtime próprio dos modelos (server.py + loop._ensure_local_servers).

Tudo offline: _endpoint_alive/_port_in_use/ensure_assets/_spawn_one são
mockados; nenhum download ou llama-server é tocado.

Roda com: uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as cfgmod  # noqa: E402
import server  # noqa: E402


class TestNeedsLocalServe(unittest.TestCase):
    def test_localhost_8091_8082(self):
        self.assertTrue(server.needs_local_serve(
            ("http://127.0.0.1:8091/v1", "http://127.0.0.1:8082/v1")))

    def test_localhost_sem_porta_ainda_e_local(self):
        self.assertTrue(server.needs_local_serve(
            ("http://localhost:8091/v1", "http://127.0.0.1:9999/v1")))

    def test_remoto_nao_sobe_nada(self):
        self.assertFalse(server.needs_local_serve(
            ("http://192.168.1.10:8091/v1", "http://192.168.1.10:8082/v1")))

    def test_misto_nao_sobe(self):
        self.assertFalse(server.needs_local_serve(
            ("http://127.0.0.1:8091/v1", "http://192.168.1.10:8082/v1")))

    def test_vazio_nao_sobe(self):
        self.assertFalse(server.needs_local_serve(("", "")))


class TestSplitHostPort(unittest.TestCase):
    def test_padrao(self):
        self.assertEqual(server._split_host_port("http://127.0.0.1:8091/v1"),
                         ("127.0.0.1", 8091))

    def test_sem_scheme(self):
        host, port = server._split_host_port("127.0.0.1:8082")
        self.assertEqual((host, port), ("127.0.0.1", 8082))


class TestServerArgs(unittest.TestCase):
    def _cfg(self, **kw):
        rt = {"host": "127.0.0.1", "ngl": 0, "threads": 4, "ctx": 4096}
        rt.update(kw)
        return {"runtime": rt}

    def test_planner_tem_jinja_sem_mmproj(self):
        args = server._server_args("planner", Path("p.gguf"), None, 8091, self._cfg())
        self.assertIn("--jinja", args)
        self.assertNotIn("--mmproj", args)
        self.assertIn("8091", args)

    def test_vision_tem_mmproj_sem_jinja(self):
        args = server._server_args("vision", Path("v.gguf"), Path("m.gguf"),
                                   8082, self._cfg())
        self.assertIn("--mmproj", args)
        self.assertNotIn("--jinja", args)

    def test_threads_zero_vira_default(self):
        args = server._server_args("planner", Path("p.gguf"), None, 8091,
                                   self._cfg(threads=0))
        i = args.index("-t") + 1
        self.assertEqual(int(args[i]), server.DEFAULT_THREADS)


class TestEnsureServers(unittest.TestCase):
    URLS = ("http://127.0.0.1:8091/v1", "http://127.0.0.1:8082/v1")

    def test_reusa_endpoint_vivo_sem_baixar(self):
        with patch.object(server, "_endpoint_alive",
                          return_value={"models": ["m"]}), \
             patch.object(server, "ensure_assets") as assets, \
             patch.object(server, "_spawn_one") as spawn:
            out = server.ensure_servers(self.URLS, {}, progress=lambda *a: None)
        self.assertEqual(out, {"planner": None, "vision": None})
        assets.assert_not_called()
        spawn.assert_not_called()

    def test_porta_ocupada_sem_endpoint_e_erro_honesto(self):
        with patch.object(server, "_endpoint_alive", return_value=None), \
             patch.object(server, "_port_in_use", return_value=True):
            with self.assertRaises(RuntimeError) as cm:
                server.ensure_servers(self.URLS, {}, progress=lambda *a: None)
        self.assertIn("ocupada", str(cm.exception))

    def test_porta_livre_baixa_e_sobe(self):
        sentinel = object()
        with patch.object(server, "_endpoint_alive", return_value=None), \
             patch.object(server, "_port_in_use", return_value=False), \
             patch.object(server, "ensure_assets",
                          return_value={"exe": "e"}) as assets, \
             patch.object(server, "_spawn_one",
                          return_value=sentinel) as spawn:
            out = server.ensure_servers(self.URLS, {}, progress=lambda *a: None)
        assets.assert_called_once()
        self.assertEqual(spawn.call_count, 2)
        self.assertIs(out["planner"], sentinel)
        self.assertIs(out["vision"], sentinel)

    def test_stop_servers_so_mata_os_nossos(self):
        killed: list[str] = []

        class FakeProc:
            def __init__(self, name):
                self.name = name

            def terminate(self):
                killed.append(self.name)

            def wait(self, timeout=None):
                pass

        server.stop_servers({"planner": None, "vision": FakeProc("vision")})
        self.assertEqual(killed, ["vision"])


class TestLoopEnsureLocal(unittest.TestCase):
    URLS = ("http://127.0.0.1:8091/v1", "http://127.0.0.1:8082/v1")

    def test_auto_start_false_nao_faz_nada(self):
        from loop import _ensure_local_servers

        cfg = {"runtime": {"auto_start": False},
               "planner": {"base_url": self.URLS[0]},
               "vision": {"base_url": self.URLS[1]}}
        with patch.object(server, "ensure_servers") as es:
            out = _ensure_local_servers(cfg)
        self.assertEqual(out, {})
        es.assert_not_called()

    def test_url_remota_nao_baixa(self):
        from loop import _ensure_local_servers

        cfg = {"runtime": {"auto_start": True},
               "planner": {"base_url": "http://192.168.1.10:8091/v1"},
               "vision": {"base_url": "http://192.168.1.10:8082/v1"}}
        with patch.object(server, "ensure_servers") as es:
            out = _ensure_local_servers(cfg)
        self.assertEqual(out, {})
        es.assert_not_called()

    def test_erro_do_runtime_vira_runtimeerror(self):
        from loop import _ensure_local_servers

        cfg = {"runtime": {"auto_start": True},
               "planner": {"base_url": "http://127.0.0.1:8091/v1"},
               "vision": {"base_url": "http://127.0.0.1:8082/v1"}}
        with patch.object(server, "ensure_servers",
                          side_effect=RuntimeError("porta ocupada")):
            with self.assertRaises(RuntimeError):
                _ensure_local_servers(cfg)


class TestRuntimeDefaults(unittest.TestCase):
    def test_config_traz_runtime(self):
        cfg = cfgmod.load("nao-existe.json")
        rt = cfg.get("runtime", {})
        self.assertTrue(rt.get("auto_start", False))
        self.assertEqual(rt.get("host"), "127.0.0.1")
        self.assertIn("ctx", rt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
