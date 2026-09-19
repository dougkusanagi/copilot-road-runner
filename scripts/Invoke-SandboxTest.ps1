<#
.SYNOPSIS
    Roda um comando de teste dentro do Windows Sandbox e retorna o resultado.

.DESCRIPTION
    Canal via pasta mapeada (.sandbox-job\<id> <-> C:\job), sem admin
    (exceto -OpenModelPorts) e sem WinRM/SSH. A CLI oficial wsb.exe
    inicia/conecta o Sandbox e dispara agent.ps1 no ExistingLogin; o host
    aguarda out\done.marker ate -TimeoutSec.

    Fluxo:
      1. escreve .sandbox-job\<id>\in\command.ps1;
      2. gera sandbox\crr-agent.local.wsb (repo->C:\crr, job->C:\job);
      3. abre via wsb start/connect, executa o agente e aguarda o marker;
      4. imprime stdout/stderr; throw se exitcode <> 0 (sem -NoThrow);
      5. fecha o Sandbox, salvo -KeepOpen (debug: conecte e inspecione).

.EXAMPLE
    .\scripts\Invoke-SandboxTest.ps1 -Command "whoami"
    Prova o canal sem instalar nada (rapido).

.EXAMPLE
    .\scripts\Invoke-SandboxTest.ps1 -Bootstrap `
        -Command "Set-Location C:\crr; uv run python -m unittest discover -s tests" `
        -TimeoutSec 1200
    Bateria completa: instala Python+uv, roda os testes, descarta tudo.

.NOTES
    Jobs ficam em .sandbox-job\ (ignorado pelo git); apague os antigos
    de vez em quando. Primeira execucao com -Bootstrap demora minutos
    (winget a cada boot — o Sandbox nao tem snapshot).
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Command,
    [switch]$Bootstrap,
    [int]$TimeoutSec = 900,
    [int]$MemoryMB = 4096,
    [switch]$KeepOpen,
    [switch]$NoThrow,
    [switch]$OpenModelPorts
)

$ErrorActionPreference = "Stop"

if ($WhatIfPreference) {
    Write-Host "WhatIf: geraria o job + .wsb e abriria via wsb.exe."
    return
}

if (-not (Get-Command wsb.exe -ErrorAction SilentlyContinue)) {
    throw "sandbox: wsb.exe ausente (a CLI requer Windows 11 24H2+)."
}

$alreadyRunning = (wsb list --raw | ConvertFrom-Json).WindowsSandboxEnvironments
if ($alreadyRunning.Count -gt 0) {
    throw "sandbox: ja existe uma instancia ativa; feche-a antes do teste."
}

if ($OpenModelPorts) {
    $elevated = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent() `
        ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
    if (-not $elevated) {
        # Antes de criar o job: sem isto ficava uma pasta orfa em .sandbox-job.
        Write-Warning "-OpenModelPorts precisa de terminal como admin."
        return
    }
}

$Repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$JobRoot = Join-Path $Repo ".sandbox-job"
$JobId = Get-Date -Format "yyyyMMdd-HHmmss"
$JobDir = Join-Path $JobRoot $JobId
$InDir = Join-Path $JobDir "in"
$OutDir = Join-Path $JobDir "out"
New-Item -ItemType Directory -Force -Path $InDir, $OutDir | Out-Null
Set-Content -LiteralPath (Join-Path $InDir "command.ps1") `
    -Value $Command -Encoding UTF8

$Wsb = Join-Path $Repo "sandbox\crr-agent.local.wsb"
$Template = @'
<Configuration>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>__REPO__</HostFolder>
      <SandboxFolder>C:\crr</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>__JOB__</HostFolder>
      <SandboxFolder>C:\job</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <MemoryInMB>__MEMORY__</MemoryInMB>
</Configuration>
'@

if ($PSCmdlet.ShouldProcess($Wsb, "Gerar .wsb do agente")) {
    $xml = $Template.Replace("__REPO__", $Repo).Replace("__JOB__", $JobDir)
    $xml = $xml.Replace("__MEMORY__", "$MemoryMB")
    $parsed = [xml]$xml  # falha aqui se o template quebrar
    $null = $parsed
    Set-Content -LiteralPath $Wsb -Value $xml -Encoding UTF8
}

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

$done = Join-Path $OutDir "done.marker"
$sandboxId = $null
try {
    if ($PSCmdlet.ShouldProcess($Wsb, "Abrir Windows Sandbox p/ job $JobId")) {
        # --config aceita o XML inline; o .wsb gravado acima e so p/ inspecao.
        $started = wsb start --config $xml --raw | ConvertFrom-Json
        $sandboxId = $started.Id
        if (-not $sandboxId) { throw "sandbox: wsb start nao devolveu um ID." }
        Start-Process -FilePath "wsb.exe" -ArgumentList @(
            "connect", "--id", $sandboxId) | Out-Null

        # SEM titulo vazio ("start \"\""): o wsb exec engole as aspas e o
        # start interpreta o exe como titulo -> filho morre em silencio
        # (ExitCode 0, nenhum marker). Caminhos sem espaco dispensam o titulo.
        $agent = "cmd.exe /d /c start powershell.exe -NoProfile " +
            "-ExecutionPolicy Bypass -File C:\crr\sandbox\agent.ps1 " +
            "-JobDir C:\job"
        # O job morre (exit 124) ANTES do host desistir: resultado parcial legivel.
        $agent += " -JobTimeoutSec $([Math]::Max(60, $TimeoutSec - 30))"
        if ($Bootstrap) { $agent += " -Bootstrap" }

        # ExistingLogin so pyautogui/UIA enxerguem o desktop interativo.
        # A sessao pode levar alguns segundos para ficar pronta apos connect.
        # try/catch: com $ErrorActionPreference='Stop' o wsb.exe falhando
        # abortaria o retry em vez de tentar de novo.
        $execDeadline = (Get-Date).AddSeconds(90)
        $dispatched = $false
        do {
            Start-Sleep -Seconds 2
            try {
                $raw = wsb exec --id $sandboxId --command $agent `
                    --run-as ExistingLogin --raw 2>$null
                if ($LASTEXITCODE -eq 0 -and $raw) {
                    $result = $raw | ConvertFrom-Json
                    $dispatched = ($result -and $result.ExitCode -eq 0)
                }
            } catch {
                $dispatched = $false
            }
        } while (-not $dispatched -and (Get-Date) -lt $execDeadline)
        if (-not $dispatched) {
            throw "sandbox: ExistingLogin nao ficou pronto em 90s."
        }
    }

    $elapsed = 0
    while (-not (Test-Path -LiteralPath $done)) {
        if ($elapsed -ge $TimeoutSec) {
            $have = (Get-ChildItem -LiteralPath $OutDir -Name `
                -ErrorAction SilentlyContinue) -join ", "
            throw ("sandbox: timeout apos {0}s (job {1}; out: [{2}]; " +
                "sem started.marker = agente nao iniciou)") `
                -f $TimeoutSec, $JobId, $have
        }
        Start-Sleep -Seconds 3
        $elapsed += 3
    }
} finally {
    if (-not $KeepOpen) {
        if ($sandboxId) {
            wsb stop --id $sandboxId --raw 2>$null | Out-Null
        }
    }
}

$code = (Get-Content -LiteralPath (Join-Path $OutDir "exitcode.txt") -Raw).Trim()
Write-Host "----- stdout (job $JobId) -----"
Get-Content -LiteralPath (Join-Path $OutDir "stdout.log") -Raw -ErrorAction SilentlyContinue |
    Write-Host
Write-Host "----- stderr -----"
Get-Content -LiteralPath (Join-Path $OutDir "stderr.log") -Raw -ErrorAction SilentlyContinue |
    Write-Host
Write-Host "exitcode: $code"

if (-not $NoThrow -and $code -ne "0") {
    throw "sandbox: comando falhou com exit $code (job $JobId)"
}
