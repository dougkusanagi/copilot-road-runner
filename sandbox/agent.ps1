<#
.SYNOPSIS
    Agente de testes DENTRO do Windows Sandbox (disparado por wsb exec).

.DESCRIPTION
    Protocolo por pasta mapeada (C:\job <-> host\.sandbox-job\<id>):
      1. opcionalmente roda bootstrap.ps1 (-Bootstrap: Python+uv+config);
      2. aguarda in\command.ps1 aparecer (o host escreve antes de abrir);
      3. executa com timeout e grava em out\: stdout.log, stderr.log,
         exitcode.txt + done.marker (sinal lido pelo host).

    Exit 124 = job estourou o timeout e foi morto.
    Exit 125 = bootstrap falhou (done.marker e gravado mesmo assim).
#>
param(
    [string]$JobDir = "C:\job",
    [switch]$Bootstrap,
    [int]$PollTimeoutSec = 300,
    [int]$JobTimeoutSec = 1200
)

$ErrorActionPreference = "Stop"

$InDir = Join-Path $JobDir "in"
$OutDir = Join-Path $JobDir "out"
New-Item -ItemType Directory -Force -Path $InDir, $OutDir | Out-Null
# Heartbeat: prova que o wsb exec iniciou o agente (host diagnostica por ele).
"started $(Get-Date -Format o)" |
    Set-Content -LiteralPath (Join-Path $OutDir "started.marker")

$stdout = Join-Path $OutDir "stdout.log"
$stderr = Join-Path $OutDir "stderr.log"
$codeFile = Join-Path $OutDir "exitcode.txt"
$done = Join-Path $OutDir "done.marker"

if ($Bootstrap) {
    Write-Host "[agent] bootstrap (Python+uv+config)..."
    try {
        & (Join-Path $PSScriptRoot "bootstrap.ps1")
    } catch {
        # Sem isto o host so veria "timeout" sem causa.
        "bootstrap falhou: $($_ | Out-String)" | Set-Content -LiteralPath $stderr
        "125" | Set-Content -LiteralPath $codeFile
        "done $(Get-Date -Format o)" | Set-Content -LiteralPath $done
        exit 125
    }
}

$cmd = Join-Path $InDir "command.ps1"
$waited = 0
while (-not (Test-Path -LiteralPath $cmd)) {
    if ($waited -ge $PollTimeoutSec) {
        throw "agent: sem job em $cmd apos ${PollTimeoutSec}s"
    }
    Start-Sleep -Seconds 2
    $waited += 2
}

# Wrapper: o exit code vem de $LASTEXITCODE dentro do processo
# (Process.ExitCode via Start-Process nao e confiavel p/ powershell).
# O wrapper roda o job num powershell filho em modo estrito
# ($ErrorActionPreference='Stop': erro vira falha) com stdout/stderr
# separados e grava o proprio exitcode.txt.
$wrapper = Join-Path $OutDir "run-wrapper.ps1"
$esc = { param($s) $s -replace "'", "''" }
$wrapperContent = @"
& powershell -NoProfile -ExecutionPolicy Bypass -Command '`$ErrorActionPreference = ''Stop''; & '$((& $esc $cmd))'' > '$((& $esc $stdout))' 2> '$((& $esc $stderr))'
`$LASTEXITCODE | Set-Content -LiteralPath '$((& $esc $codeFile))'
"@
Set-Content -LiteralPath $wrapper -Value $wrapperContent -Encoding UTF8

Write-Host "[agent] executando job..."
$p = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`"" `
    -PassThru

$elapsed = 0
while (-not $p.HasExited -and $elapsed -lt $JobTimeoutSec) {
    Start-Sleep -Seconds 2
    $elapsed += 2
}
if (-not $p.HasExited) {
    try { $p.Kill() } catch {}
    Start-Sleep -Seconds 1
    "124" | Set-Content -LiteralPath $codeFile
    Write-Host "[agent] timeout apos ${JobTimeoutSec}s (exit 124)."
} else {
    $code = (Get-Content -LiteralPath $codeFile -Raw -ErrorAction SilentlyContinue)
    Write-Host "[agent] fim com exit $($code.Trim())."
}
"done $(Get-Date -Format o)" | Set-Content -LiteralPath $done
