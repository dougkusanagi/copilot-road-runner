#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Prepara a VM de teste do copilot-road-runner no Hyper-V (Windows 11 Pro).

.DESCRIPTION
    Idempotente: pode rodar de novo sem duplicar nada. Cria o VHDX/VM se nao
    existirem, ajusta CPU/RAM, liga o Enhanced Session Mode no host e (opcional)
    abre as portas dos modelos no firewall do HOST.

    Topologia do projeto: o agente roda DENTRO do guest; os modelos
    (llama-server: planner 8091 + vision 8082) ficam no HOST com GPU.
    Detalhes e loop diario em docs/hyper-v-test-vm.md.

.EXAMPLE
    .\New-TestVm.ps1 -IsoPath C:\ISOs\Win11.iso
    Cria a VM e anexa a ISO para a instalacao do Windows guest.

.EXAMPLE
    .\New-TestVm.ps1 -OpenModelPorts -CreateCheckpoint
    Libera 8091/8082 no firewall e salva o snapshot "clean"
    (rode DEPOIS de instalar o Windows + deps no guest).

.EXAMPLE
    .\New-TestVm.ps1 -WhatIf
    Mostra o que seria feito sem alterar nada.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$VmName = "crr-test",
    [string]$SwitchName = "Default Switch",
    [string]$VmDir = "C:\VMs\crr-test",
    [string]$IsoPath = "",
    [int]$MemoryGB = 4,
    [int]$CpuCount = 2,
    [switch]$OpenModelPorts,
    [switch]$CreateCheckpoint
)

$ErrorActionPreference = "Stop"

# 1. Hyper-V habilitado?
$hv = Get-WindowsOptionalFeature -Online -FeatureName "Microsoft-Hyper-V-All"
if ($hv.State -ne "Enabled") {
    Write-Warning "Hyper-V nao esta habilitado. Rode (admin) e reinicie:"
    Write-Host "  Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All"
    return
}

# 2. Switch existente?
$sw = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
if (-not $sw) {
    throw "Switch '$SwitchName' nao encontrado. Crie um no Virtual Switch Manager do Hyper-V."
}

# 3. Diretorio + VHDX dinamico.
if (-not (Test-Path -LiteralPath $VmDir)) {
    if ($PSCmdlet.ShouldProcess($VmDir, "Criar diretorio da VM")) {
        New-Item -ItemType Directory -Path $VmDir | Out-Null
    }
}
$vhd = Join-Path $VmDir ("{0}.vhdx" -f $VmName)
if (-not (Test-Path -LiteralPath $vhd)) {
    if ($PSCmdlet.ShouldProcess($vhd, "Criar VHDX dinamico 60GB")) {
        New-VHD -Path $vhd -SizeBytes 60GB -Dynamic | Out-Null
    }
}

# 4. VM (cria ou ajusta; nunca duplica).
$vm = Get-VM -Name $VmName -ErrorAction SilentlyContinue
if (-not $vm) {
    if ($PSCmdlet.ShouldProcess($VmName, "Criar VM Gen2")) {
        $vm = New-VM -Name $VmName -Generation 2 `
            -MemoryStartupBytes ([long]$MemoryGB * 1GB) `
            -VHDPath $vhd -SwitchName $SwitchName
        Set-VMProcessor -VMName $VmName -Count $CpuCount
        Set-VM -Name $VmName -AutomaticCheckpointsEnabled $false -CheckpointType Standard
        Enable-VMIntegrationService -VMName $VmName -Name "Guest Service Interface"
    }
}
else {
    if ($PSCmdlet.ShouldProcess($VmName, "Ajustar CPU/RAM")) {
        if ($vm.State -ne "Off") { Stop-VM -Name $VmName -Force }
        Set-VM -Name $VmName -MemoryStartupBytes ([long]$MemoryGB * 1GB)
        Set-VMProcessor -VMName $VmName -Count $CpuCount
    }
}

# 5. ISO (so com VM desligada; so instala uma vez).
if ($IsoPath) {
    if (-not (Test-Path -LiteralPath $IsoPath)) { throw "ISO nao encontrada: $IsoPath" }
    if ($PSCmdlet.ShouldProcess($VmName, "Anexar ISO")) {
        $dvd = Get-VMDvdDrive -VMName $VmName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($dvd) { Set-VMDvdDrive -VMName $VmName -Path $IsoPath }
        else { Add-VMDvdDrive -VMName $VmName -Path $IsoPath }
        Set-VMFirmware -VMName $VmName `
            -FirstBootDevice (Get-VMDvdDrive -VMName $VmName | Select-Object -First 1)
    }
}

# 6. Enhanced Session no host (copy/paste + resolucao livre no console).
if ($PSCmdlet.ShouldProcess("host Hyper-V", "Habilitar Enhanced Session Mode")) {
    Set-VMHost -EnableEnhancedSessionMode $true
}

# 7. Firewall do HOST para os modelos (guest -> host).
if ($OpenModelPorts) {
    foreach ($port in @(8091, 8082)) {
        $rule = "crr-model-{0}" -f $port
        if (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue) {
            Write-Host "Firewall: regra $rule ja existe."
        }
        elseif ($PSCmdlet.ShouldProcess($rule, "Liberar TCP $port inbound")) {
            New-NetFirewallRule -DisplayName $rule -Direction Inbound `
                -Protocol TCP -LocalPort $port -Action Allow | Out-Null
        }
    }
}

# 8. Snapshot limpo (rode DEPOIS do guest pronto: Windows + Python + projeto).
if ($CreateCheckpoint) {
    if ($PSCmdlet.ShouldProcess($VmName, "Checkpoint 'clean'")) {
        Checkpoint-VM -Name $VmName -SnapshotName "clean"
    }
}

Write-Host ""
Write-Host "OK: VM '$VmName' pronta. Proximos passos em docs/hyper-v-test-vm.md"
