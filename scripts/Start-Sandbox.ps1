<#
.SYNOPSIS
    Abre o Windows Sandbox com o repo mapeado (sem precisar de admin).

.DESCRIPTION
    Gera sandbox\crr.local.wsb (local, ignorado pelo git) com o caminho
    real do repo e abre o Sandbox pela CLI oficial wsb.exe. Depois de
    conectar a sessao interativa, wsb exec inicia bootstrap.ps1 no
    ExistingLogin: instala Python+uv, roda `uv sync` e preenche o IP.

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

if (-not (Get-Command wsb.exe -ErrorAction SilentlyContinue)) {
    throw "sandbox: wsb.exe ausente (a CLI requer Windows 11 24H2+)."
}

$alreadyRunning = (wsb list --raw | ConvertFrom-Json).WindowsSandboxEnvironments
if ($alreadyRunning.Count -gt 0) {
    throw "sandbox: ja existe uma instancia ativa; feche-a antes de abrir outra."
}

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

if ($PSCmdlet.ShouldProcess($Wsb, "Abrir Windows Sandbox via wsb.exe")) {
    $started = wsb start --config $xml --raw | ConvertFrom-Json
    $sandboxId = $started.Id
    if (-not $sandboxId) { throw "sandbox: wsb start nao devolveu um ID." }
    Start-Process -FilePath "wsb.exe" -ArgumentList @(
        "connect", "--id", $sandboxId) | Out-Null

    # SEM titulo vazio no start (mesmo motivo do invoker: wsb exec engole
    # as aspas e o filho morre em silencio).
    $bootstrap = "cmd.exe /d /c start powershell.exe -NoProfile " +
        "-ExecutionPolicy Bypass -NoExit -File C:\crr\sandbox\bootstrap.ps1"
    $deadline = (Get-Date).AddSeconds(90)
    $dispatched = $false
    do {
        Start-Sleep -Seconds 2
        try {
            $raw = wsb exec --id $sandboxId --command $bootstrap `
                --run-as ExistingLogin --raw 2>$null
            if ($LASTEXITCODE -eq 0 -and $raw) {
                $result = $raw | ConvertFrom-Json
                $dispatched = ($result -and $result.ExitCode -eq 0)
            }
        } catch {
            $dispatched = $false
        }
    } while (-not $dispatched -and (Get-Date) -lt $deadline)
    if (-not $dispatched) {
        wsb stop --id $sandboxId --raw 2>$null | Out-Null
        throw "sandbox: ExistingLogin nao ficou pronto em 90s."
    }
}

Write-Host ""
Write-Host "OK: Sandbox abrindo. Detalhes em docs/sandbox-test-env.md"
