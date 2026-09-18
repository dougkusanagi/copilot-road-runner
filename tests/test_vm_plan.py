"""Plano Hyper-V (docs/hyper-v-test-vm.md): artefatos testáveis sem Hyper-V.

Cobre o que o plano promete sem exigir admin, VM ou modelos online:
  - scripts/ + config.vm.example.json existem e são idempotentes/parseáveis
  - portas 8091/8082, VM "crr-test", snapshot "clean", Default Switch
  - config.vm.json ignorado, mas o exemplo versionado
  - main.py aceita --config/--max-steps/--self-test (loop diário do doc)
  - salvaguardas: FAILSAFE + hotkey ctrl+alt+esc
  - docs referencia todos os artefatos (sem link quebrado)

Roda com: uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NEW_VM = ROOT / "scripts" / "New-TestVm.ps1"
RESET_VM = ROOT / "scripts" / "Reset-TestVm.ps1"
DOC = ROOT / "docs" / "hyper-v-test-vm.md"
VM_EXAMPLE = ROOT / "config.vm.example.json"
GITIGNORE = ROOT / ".gitignore"


class TestVmPlanFiles(unittest.TestCase):
    def test_arquivos_existem(self):
        for p in (NEW_VM, RESET_VM, DOC, VM_EXAMPLE):
            self.assertTrue(p.is_file(), f"faltando: {p.name}")

    def test_example_valido_e_aponta_p_host(self):
        cfg = json.loads(VM_EXAMPLE.read_text(encoding="utf-8"))
        self.assertIn("HOST_IP", cfg["planner"]["base_url"])
        self.assertIn("8091", cfg["planner"]["base_url"])
        self.assertIn("HOST_IP", cfg["vision"]["base_url"])
        self.assertIn("8082", cfg["vision"]["base_url"])
        self.assertEqual(cfg["max_steps"], 4)  # doc: comece com 4
        self.assertEqual(cfg["screenshot_max_width"], 1024)
        self.assertEqual(cfg["stop_hotkey"], "ctrl+alt+esc")

    def test_example_carrega_via_config_py(self):
        import config as cfgmod

        cfg = cfgmod.load(VM_EXAMPLE)  # merge com defaults, sem quebrar
        self.assertEqual(cfg["max_steps"], 4)
        self.assertEqual(cfg["stop_hotkey"], "ctrl+alt+esc")

    def test_gitignore(self):
        ign = GITIGNORE.read_text(encoding="utf-8").splitlines()
        self.assertIn("config.vm.json", ign)
        # o exemplo PRECISA ser versionado (guest copia p/ config.vm.json)
        self.assertNotIn("config.vm.example.json", ign)


class TestVmScripts(unittest.TestCase):
    def test_new_testvm_idempotente_e_parametros(self):
        src = NEW_VM.read_text(encoding="utf-8")
        self.assertIn("#Requires -RunAsAdministrator", src)
        self.assertIn("SupportsShouldProcess", src)  # -WhatIf
        for param in ('$VmName = "crr-test"', '$SwitchName = "Default Switch"',
                      "[int]$MemoryGB = 4", "[int]$CpuCount = 2",
                      "[switch]$OpenModelPorts", "[switch]$CreateCheckpoint",
                      "$IsoPath"):
            self.assertIn(param, src, f"param ausente: {param}")
        for needle in ("8091", "8082",  # firewall guest->host
                       "60GB -Dynamic",  # VHDX dinâmico
                       "EnableEnhancedSessionMode",  # copy/paste console
                       'Checkpoint-VM -Name $VmName -SnapshotName "clean"',
                       "Remove-VMSnapshot",  # re-criar clean sem duplicar
                       "Get-VMIntegrationService",  # best-effort, sem abortar
                       "Get-VM -Name $VmName",  # nunca duplica
                       "New-VHD", "New-VM -Name $VmName -Generation 2"):
            self.assertIn(needle, src, f"trecho ausente: {needle}")
        # sem Enable duro que aborta o script se o nome do servico variar
        self.assertNotIn('Enable-VMIntegrationService -VMName $VmName -Name "Guest Service Interface"',
                         src)

    def test_reset_testvm(self):
        src = RESET_VM.read_text(encoding="utf-8")
        self.assertIn("#Requires -RunAsAdministrator", src)
        self.assertIn("SupportsShouldProcess", src)
        self.assertIn('$VmName = "crr-test"', src)
        self.assertIn('$SnapshotName = "clean"', src)
        self.assertIn("Restore-VMSnapshot", src)
        self.assertIn("Start-VM -Name $VmName", src)

    def test_powershell_parse_sem_executar(self):
        """Parser oficial do PS: erro de sintaxe falha aqui, sem precisar de admin/Hyper-V."""
        for ps1 in (NEW_VM, RESET_VM):
            cmd = (
                "$errs=$null; $toks=$null; "
                "[void][System.Management.Automation.Language.Parser]::"
                f"ParseFile('{ps1}', [ref]$toks, [ref]$errs); "
                "$errs.Count"
            )
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd],
                    capture_output=True, text=True, timeout=30)
            except (FileNotFoundError, subprocess.SubprocessError) as e:
                self.skipTest(f"powershell indisponível: {e}")
            self.assertEqual(out.returncode, 0, out.stderr[:500])
            self.assertEqual(out.stdout.strip(), "0",
                             f"erro de sintaxe em {ps1.name}: {out.stdout}{out.stderr[:500]}")


class TestVmCliESalvaguardas(unittest.TestCase):
    def test_main_help_tem_flags_do_loop_diario(self):
        out = subprocess.run(
            [sys.executable, "main.py", "--help"],
            capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stderr[:500])
        for flag in ("--config", "--max-steps", "--self-test",
                     "--planner-url", "--vision-url", "--locate"):
            self.assertIn(flag, out.stdout)

    def test_main_selftest_help_nao_clica(self):
        import main  # noqa: F401  (import não executa ação)
        import actions
        import safety

        self.assertTrue(actions.pyautogui.FAILSAFE)
        self.assertEqual(safety.HOTKEY, "ctrl+alt+esc")

    def test_docs_referencia_tudo(self):
        doc = DOC.read_text(encoding="utf-8")
        for needle in ("New-TestVm.ps1", "Reset-TestVm.ps1",
                       "config.vm.example.json", "config.vm.json",
                       "--self-test", "--max-steps 4", "--config config.vm.json",
                       "8091", "8082", "clean", "100%",
                       "FAILSAFE"):
            self.assertIn(needle, doc, f"docs sem: {needle}")
        # hotkey aparece como `Ctrl+Alt+Esc` no texto humano; compara sem case
        self.assertIn("ctrl+alt+esc", doc.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
