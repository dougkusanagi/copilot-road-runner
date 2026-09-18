<#
.SYNOPSIS
    Roda um comando de teste dentro do Windows Sandbox e retorna o resultado.

.DESCRIPTION
    Canal via pasta mapeada (.sandbox-job\<id> <-> C:\job), sem admin
    (exceto -OpenModelPorts) e sem remote shell — o Sandbox nao expoe
    WinRM; o agent.ps1 (LogonCommand) executa in\command.ps1 e o host
    aguarda out\done.marker ate -TimeoutSec.

    Fluxo:
      1. escreve .sandbox-job\<id>\in\command.ps1;
      2. gera sandbox\crr-agent.local.wsb (repo->C:\crr, job->C:\job);
      3. abre o Sandbox e aguarda o done.marker;
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
    Write-Host "WhatIf: geraria o job + .wsb e abriria o Sandbox."
    return
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
$logon = "powershell -ExecutionPolicy Bypass -NoExit -File " +
    "C:\crr\sandbox\agent.ps1 -JobDir C:\job"
if ($Bootstrap) { $logon += " -Bootstrap" }

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
  <LogonCommand>
    <Command>__LOGON__</Command>
  </LogonCommand>
  <MemoryInMB>__MEMORY__</MemoryInMB>
</Configuration>
'@

if ($PSCmdlet.ShouldProcess($Wsb, "Gerar .wsb do agente")) {
    $xml = $Template.Replace("__REPO__", $Repo).Replace("__JOB__", $JobDir)
    $xml = $xml.Replace("__LOGON__", $logon).Replace("__MEMORY__", "$MemoryMB")
    $parsed = [xml]$xml  # falha aqui se o template quebrar
    $null = $parsed
    Set-Content -LiteralPath $Wsb -Value $xml -Encoding UTF8
}

if ($OpenModelPorts) {
    $elevated = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent() `
        ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
    if (-not $elevated) {
        Write-Warning "-OpenModelPorts precisa de terminal como admin."
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

if ($PSCmdlet.ShouldProcess($Wsb, "Abrir Windows Sandbox p/ job $JobId")) {
    Invoke-Item -LiteralPath $Wsb
}

$done = Join-Path $OutDir "done.marker"
try {
    $elapsed = 0
    while (-not (Test-Path -LiteralPath $done)) {
        if ($elapsed -ge $TimeoutSec) {
            $have = (Get-ChildItem -LiteralPath $OutDir -Name `
                -ErrorAction SilentlyContinue) -join ", "
            throw ("sandbox: timeout apos {0}s (job {1}; out: [{2}]; " +
                "sem started.marker = LogonCommand nao rodou)") `
                -f $TimeoutSec, $JobId, $have
        }
        Start-Sleep -Seconds 3
        $elapsed += 3
    }
} finally {
    if (-not $KeepOpen) {
        Get-Process -Name "WindowsSandboxClient" -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
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
