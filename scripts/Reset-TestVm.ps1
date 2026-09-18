#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Restaura a VM de teste para o snapshot limpo e a reinicia.

.DESCRIPTION
    Loop diario de testes do copilot-road-runner: depois de cada bateria
    (ou de qualquer teste destrutivo), volta o guest ao estado "clean"
    em segundos. Uso junto com scripts/New-TestVm.ps1.

.EXAMPLE
    .\Reset-TestVm.ps1
    Restaura "crr-test" para o snapshot "clean" e da Start.

.EXAMPLE
    .\Reset-TestVm.ps1 -SnapshotName "pre-run" -WhatIf
    Mostra o que seria feito sem alterar nada.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$VmName = "crr-test",
    [string]$SnapshotName = "clean"
)

$ErrorActionPreference = "Stop"

$vm = Get-VM -Name $VmName -ErrorAction Stop
$snap = Get-VMSnapshot -VMName $VmName -Name $SnapshotName -ErrorAction SilentlyContinue
if (-not $snap) {
    throw "Snapshot '$SnapshotName' nao existe em '$VmName'. Crie com: .\New-TestVm.ps1 -CreateCheckpoint"
}

if ($PSCmdlet.ShouldProcess("$VmName -> $SnapshotName", "Restaurar snapshot e iniciar")) {
    if ($vm.State -ne "Off") { Stop-VM -Name $VmName -Force }
    Restore-VMSnapshot -VMName $VmName -Name $SnapshotName -Confirm:$false
    Start-VM -Name $VmName
    Write-Host "OK: '$VmName' restaurado para '$SnapshotName' e iniciado."
}
