<#
.SYNOPSIS
    Abre o Windows Sandbox com o repo mapeado (sem precisar de admin).

.DESCRIPTION
    Gera sandbox\crr.local.wsb (local, ignorado pelo git) com o caminho
    real do repo e abre o Sandbox. O LogonCommand do .wsb executa
    C:\crr\sandbox\bootstrap.ps1 sozinho: instala Python+uv, roda
    `uv sync` e preenche o IP do host no config.

    Topologia: o agente roda DENTRO do sandbox; os modelos
    (llama-server: planner 8091 + vision 8082) ficam no HOST com GPU.
    Detalhes e loop diario em docs/sandbox-test-env.md.

.EXAMPLE
    .\scripts\Start-Sandbox.ps1
    Gera o .wsb e abre o Sandbox.

.EXAMPLE
    .\scripts\Start-Sandbox.ps1 -OpenModelPorts -WhatIf
    Mostra o que seria feito, incluindo as regras de firewall (admin).

.NOTES
    Nao requer elevacao, EXCETO com -OpenModelPorts (firewall do host).
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$OpenModelPorts,
    [int]$MemoryMB = 4096
)

$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Wsb = Join-Path $Repo "sandbox\crr.local.wsb"

$Template = @'
<Configuration>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>__REPO__</HostFolder>
      <SandboxFolder>C:\crr</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell -ExecutionPolicy Bypass -NoExit -File C:\crr\sandbox\bootstrap.ps1</Command>
  </LogonCommand>
  <MemoryInMB>__MEMORY__</MemoryInMB>
</Configuration>
'@

if ($PSCmdlet.ShouldProcess($Wsb, "Gerar .wsb com o caminho do repo")) {
    $xml = $Template.Replace("__REPO__", $Repo).Replace("__MEMORY__", "$MemoryMB")
    $parsed = [xml]$xml  # falha aqui se o template quebrar
    Set-Content -LiteralPath $Wsb -Value $xml -Encoding UTF8
    Write-Host "Wsb gerado: $Wsb"
}

if ($OpenModelPorts) {
    $elevated = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent() `
        ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
    if (-not $elevated) {
        Write-Warning "-OpenModelPorts precisa de terminal como admin. Rode de novo elevado."
        return
    }
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

if ($PSCmdlet.ShouldProcess($Wsb, "Abrir Windows Sandbox")) {
    Invoke-Item -LiteralPath $Wsb
}

Write-Host ""
Write-Host "OK: Sandbox abrindo. Detalhes em docs/sandbox-test-env.md"
