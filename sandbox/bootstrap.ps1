<#
.SYNOPSIS
    Prepara o ambiente DENTRO do Windows Sandbox (roda sozinho via LogonCommand).

.DESCRIPTION
    Idempotente por boot: instala Python 3.12 + uv (via winget), roda
    `uv sync` no projeto mapeado em C:\crr, detecta o IP do HOST
    (gateway da rota default) e gera C:\crr\config.sandbox.json a partir
    do exemplo, trocando HOST_IP automaticamente.

    O Sandbox descarta TUDO ao fechar: este script re-executa a cada
    abertura. Nada aqui exige review — so instalacao e configuracao.
#>
$ErrorActionPreference = "Stop"

$Repo = "C:\crr"
$Example = Join-Path $Repo "sandbox\config.sandbox.example.json"
$Target = Join-Path $Repo "config.sandbox.json"

Write-Host "[bootstrap] verificando winget..."
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) { throw "winget nao encontrado neste Sandbox." }

function Ensure-Package($Id) {
    $found = winget list --id $Id --exact 2>$null | Select-String $Id
    if ($found) { Write-Host "[bootstrap] $Id ja instalado." }
    else {
        Write-Host "[bootstrap] instalando $Id..."
        winget install --id $Id --exact --silent `
            --accept-source-agreements --accept-package-agreements
    }
}

Ensure-Package "Python.Python.3.12"
Ensure-Package "astral-sh.uv"

# Atualiza o PATH da sessao (winget instala em User ou Machine).
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") +
    ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "[bootstrap] uv sync em $Repo..."
Set-Location -LiteralPath $Repo
uv sync

# IP do host = gateway da rota default (muda a cada boot do Sandbox).
$HostIp = $null
try {
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
        Select-Object -First 1
    $HostIp = $route.NextHop
} catch {
    Write-Warning "[bootstrap] gateway nao detectado; edite HOST_IP a mao."
}

if (Test-Path -LiteralPath $Target) {
    Write-Host "[bootstrap] $Target ja existe; mantido."
} else {
    Copy-Item -LiteralPath $Example -Destination $Target
    Write-Host "[bootstrap] criado $Target a partir do exemplo."
}

if ($HostIp) {
    (Get-Content -LiteralPath $Target -Raw).Replace("HOST_IP", $HostIp) |
        Set-Content -LiteralPath $Target -NoNewline
    Write-Host "[bootstrap] HOST_IP -> $HostIp"
}

Write-Host ""
Write-Host "[bootstrap] pronto. Proximos passos (neste Sandbox):"
Write-Host "  uv run python main.py --self-test          # sem clicar em nada"
Write-Host '  uv run python main.py "..." --config config.sandbox.json --max-steps 4'
