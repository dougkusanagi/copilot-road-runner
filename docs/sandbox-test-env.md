# Sandbox de teste — desenvolver sem atrapalhar o uso do PC

> Host: **Windows 11 Pro**. O agente (`pyautogui`/`pywinauto`) rouba mouse e teclado
> de quem o executa — por isso ele roda **dentro do Sandbox**, e o host fica livre.

## Topologia

* **HOST (seu PC, com GPU):** `llama-server` do planner (`:8091`, MiniCPM5-1B)
  + visão (`:8082`, Vocaela-2) + IDE. Nada que clique na tela roda aqui.
* **SANDBOX:** só o agente leve — o repo é mapeado em `C:\crr`
  (`main.py`, `loop.py`, `uia.py`, `actions.py`, `tools.py`)
  + `config.sandbox.json` com o IP do host preenchido automaticamente.
* **Isolamento:** o `pyautogui` do Sandbox só enxerga o desktop do Sandbox.
  Fechar o Sandbox **descarta tudo** — cada abertura é um ambiente limpo.

## Pré-requisitos

* Windows 11 Pro/Edu com virtualização ativa na BIOS/UEFI.
* Recurso **Windows Sandbox** habilitado (uma vez, sem admin no uso diário).
* ~4GB RAM livre p/ o Sandbox (ajuste com `-MemoryMB` se precisar).

## Setup (uma vez no host)

```powershell
.\scripts\Start-Sandbox.ps1 -OpenModelPorts   # terminal como admin, 1x
```

Suba os dois `llama-server` ouvindo na rede (`--host 0.0.0.0`),
não só em `127.0.0.1` — o Sandbox alcança o host pelo gateway.

## Loop diário de testes

```powershell
# uso diário: NÃO precisa de admin
.\scripts\Start-Sandbox.ps1
```

O launcher usa a CLI oficial `wsb.exe`: `start` cria a VM, `connect` abre
a sessão e `exec -r ExistingLogin` inicia `sandbox\bootstrap.ps1` dentro
do Sandbox. Ele instala Python 3.12 + `uv` (via winget), roda
`uv sync`, detecta o IP do host (gateway da rota default) e gera
`config.sandbox.json` a partir de `sandbox\config.sandbox.example.json`.

Dentro do Sandbox, sempre nesta ordem:

```powershell
uv run python main.py --self-test          # sem clicar em nada
uv run python main.py "..." --config config.sandbox.json --max-steps 4
```

Fechou o Sandbox, tudo é descartado — abra de novo para a próxima bateria limpa.

## Arquivos

| Arquivo | Papel |
|---|---|
| `scripts\Start-Sandbox.ps1` | gera `sandbox\crr.local.wsb` (local, ignorado pelo git) e abre o Sandbox |
| `sandbox\bootstrap.ps1` | setup automático dentro do Sandbox (Python+uv+config) |
| `sandbox\config.sandbox.example.json` | modelo versionado; `config.sandbox.json` é local e ignorado |
| `sandbox\crr.local.wsb` | gerado por máquina; nunca commitar |
| `scripts\Invoke-SandboxTest.ps1` | host: roda um comando no Sandbox e devolve o resultado (uso do agente) |
| `sandbox\agent.ps1` | runner dentro do Sandbox: executa o job e grava o resultado |
| `.sandbox-job\` | inbox/outbox dos jobs; local, ignorado pelo git |

## Testes executados pelo agente (eu rodo no Sandbox)

O Sandbox não expõe WinRM/SSH, então o canal de dados é pasta mapeada:
o host escreve o comando e usa `wsb exec -r ExistingLogin` para iniciar
o `agent.ps1`; ele executa
e o host aguarda o `done.marker`.

```powershell
# prova o canal (rápido, sem instalar nada)
.\scripts\Invoke-SandboxTest.ps1 -Command "whoami"

# bateria completa com Python+uv (primeira vez demora minutos: winget)
.\scripts\Invoke-SandboxTest.ps1 -Bootstrap `
    -Command "Set-Location C:\crr; uv run python -m unittest discover -s tests" `
    -TimeoutSec 1200

# debug interativo: mantém o Sandbox aberto após o job
.\scripts\Invoke-SandboxTest.ps1 -Command "whoami" -KeepOpen
```

Protocolo (`.sandbox-job\<id>\` ↔ `C:\job`):

| Lado | Arquivo | Papel |
|---|---|---|
| host → sandbox | `in\command.ps1` | comando a executar |
| sandbox → host | `out\stdout.log` / `out\stderr.log` | saída capturada |
| sandbox → host | `out\exitcode.txt` | `0` = ok; `124` = timeout do job (via `$LASTEXITCODE` no wrapper) |
| sandbox → host | `out\done.marker` | sinal de conclusão (host faz poll até `-TimeoutSec`) |
| sandbox → host | `out\started.marker` | heartbeat: prova que o `wsb exec` iniciou o agente |

## Salvaguardas

* `pyautogui.FAILSAFE` ativo: canto superior-esquerdo **do Sandbox** aborta;
  `ctrl+alt+esc` (dentro do Sandbox) também para o loop.
* Comece com `--max-steps 4`; aumente só após verde consistente.
* Nunca rode o agente no host enquanto usa o PC — é exatamente o que o Sandbox evita.

## Troubleshooting

| Sintoma | Causa provável / fix |
|---|---|
| Sandbox não alcança `:8091`/`:8082` | `llama-server` preso em `127.0.0.1` → subir com `--host 0.0.0.0`; rodar com `-OpenModelPorts` em terminal admin |
| `HOST_IP` não resolvido | `bootstrap.ps1` não achou o gateway → rode `Get-NetRoute -DestinationPrefix "0.0.0.0/0"` no Sandbox e edite `config.sandbox.json` à mão |
| winget lento na primeira abertura | normal: Python+uv instalam a cada boot (Sandbox não tem snapshot); deixe o `bootstrap.ps1` terminar |
| job do agente sem resposta | `Invoke-SandboxTest.ps1` estourou `-TimeoutSec` → aumente o timeout; com `-KeepOpen`, abra o Sandbox e leia `C:\job\out\` |
| job sem nem `started.marker` | `wsb exec` não iniciou o agente ou ele falhou antes do heartbeat; confira o erro do invoker e `C:\job\out\` |
| `LogonCommand` nunca dispara (mapeamento ok, nenhum console abre) | regressão confirmada nesta máquina (Windows 11 25H2 build 26200.9457). O protocolo não depende mais dele: usa `wsb start/connect/exec/stop` (CLI disponível desde 24H2). |
| Sandbox órfão (Server/RemoteSession vivos, sem janela) | o invoker atual encerra pelo ID com `wsb stop`; para órfão antigo, obtenha o ID com `wsb list --raw` e use `wsb stop --id ID` (nunca matar `vmwp` às cegas — WSL usa outro) |
| `sandbox: ja existe uma instancia ativa` | só um Sandbox por vez; feche a sessão existente. O invoker não encerra uma instância que não criou. |
| `.sandbox-job\` crescendo | jobs antigos não são apagados sozinhos → limpe a pasta de vez em quando |
| Sandbox não abre | recurso desabilitado ou sem virtualização → habilite Windows Sandbox + VT-x/AMD-V na BIOS |
| Clique deslocado no Sandbox | escala de DPI ≠ 100% no Sandbox — fixe 100% |
