# Sandbox de teste — só para testes dev (o uso real é local, sem parâmetros)

> **Escopo:** este guia descreve os scripts e o baseline implementados hoje.
> A evolução dos perfis de modelos e a bateria de avaliação estão no
> [plano vigente de refatoração](plano-agente-generico-2026-09-20.md).
> Dois endpoints/modelos abaixo não são requisito do futuro perfil unificado.
> Os modelos continuam na GPU do host e os cliques no Sandbox; não medir VRAM
> pela GPU virtual do Sandbox nem executar testes de interação no host.

> O sistema roda **no host por padrão** (`uv run python main.py "..."`,
> sem `--config`): o runtime próprio (`server.py`) baixa os modelos na 1ª
> vez e sobe `:8091`/`:8082` sozinho. O Sandbox existe para um único fim:
> **testes de desenvolvimento com cliques descartáveis**, acionado apenas
> pelos scripts (`Start-Sandbox.ps1` manual,
> `Invoke-SandboxTest.ps1` automatizado). Nunca rode `--config
> config.sandbox.json` no host — esse arquivo só existe dentro do Sandbox.

## Topologia

* **HOST (seu PC):** runtime próprio dos modelos — planner (`:8091`,
  MiniCPM5-1B) + visão (`:8082`, Vocaela-2), gerenciado por `server.py`
  (baixa `llama-server` + GGUFs p/ `models/` na 1ª vez, reusa depois;
  portas fora do padrão, sem conflito com Ollama/LM Studio) + IDE +
  **o agente real, que roda aqui por padrão**.
* **SANDBOX (só testes dev):** cópia leve do agente — o repo é mapeado em
  `C:\crr` (`main.py`, `loop.py`, `uia.py`, `actions.py`, `tools.py`)
  + `config.sandbox.json` com o IP do host preenchido automaticamente.
  Ele **reusa** os modelos do host via gateway (`HOST_IP`): nada é
  baixado nem subido dentro do Sandbox.
* **Isolamento:** o `pyautogui` do Sandbox só enxerga o desktop do Sandbox.
  Fechar o Sandbox **descarta tudo** — cada abertura é um ambiente limpo.

## Pré-requisitos

* Windows 11 Pro/Edu com virtualização ativa na BIOS/UEFI.
* Recurso **Windows Sandbox** habilitado (uma vez, sem admin no uso diário).
* ~4GB RAM livre p/ o Sandbox (ajuste com `-MemoryMB` se precisar).

## Setup (uma vez no host, só p/ testes no Sandbox)

```powershell
.\scripts\Start-Sandbox.ps1 -OpenModelPorts   # terminal como admin, 1x
```

O runtime próprio já pode expor os modelos na rede (`uv run python -m
server --host 0.0.0.0`), mas o padrão local (`127.0.0.1`, usado pelo uso
real) não é alcançável de dentro do Sandbox — ele alcança o host pelo
gateway. Por isso os testes no Sandbox exigem o bind aberto + a regra de
firewall (`-OpenModelPorts`).

## Loop de testes (sempre DENTRO do Sandbox, via scripts)

```powershell
# uso em teste: NÃO precisa de admin
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
| sandbox → host | `out\exitcode.txt` | `0` = ok; `124` = timeout do job (via `$LASTEXITCODE` no wrapper); `125` = `bootstrap.ps1` falhou (causa em `stderr.log`) |
| sandbox → host | `out\done.marker` | sinal de conclusão (host faz poll até `-TimeoutSec`) |
| sandbox → host | `out\started.marker` | heartbeat: prova que o `wsb exec` iniciou o agente |

## Salvaguardas

* Uso real roda no host: não use mouse/teclado enquanto o agente age.
  `pyautogui.FAILSAFE` ativo: canto superior-esquerdo aborta (no host, o
  do host; no Sandbox, o **do Sandbox**);
  `ctrl+alt+esc` (na máquina onde o agente roda) também para o loop.
* Comece com `--max-steps 4`; aumente só após verde consistente.
* Testes dev com cliques vão no Sandbox — é exatamente o que ele evita:
  roubar o mouse/teclado do seu uso no host.

## Troubleshooting

| Sintoma | Causa provável / fix |
|---|---|
| Sandbox não alcança `:8091`/`:8082` | runtime preso em `127.0.0.1` → expor com `uv run python -m server --host 0.0.0.0`; rodar com `-OpenModelPorts` em terminal admin |
| `HOST_IP` não resolvido | `bootstrap.ps1` não achou o gateway → rode `Get-NetRoute -DestinationPrefix "0.0.0.0/0"` no Sandbox e edite `config.sandbox.json` à mão |
| `.venv` do host "trocou de Python" após um Sandbox | regressão antiga: `uv sync` em `C:\crr` escrevia no `.venv` mapeado. Hoje o bootstrap usa `UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\crr-venv` (+ `UV_CACHE_DIR`); se voltar, confira essas variáveis no Sandbox |
| winget lento na primeira abertura | normal: Python+uv instalam a cada boot (Sandbox não tem snapshot); deixe o `bootstrap.ps1` terminar |
| job do agente sem resposta | `Invoke-SandboxTest.ps1` estourou `-TimeoutSec` → aumente o timeout; com `-KeepOpen`, abra o Sandbox e leia `C:\job\out\` |
| job sem nem `started.marker` | `wsb exec` não iniciou o agente ou ele falhou antes do heartbeat; confira o erro do invoker e `C:\job\out\` |
| `LogonCommand` nunca dispara (mapeamento ok, nenhum console abre) | regressão confirmada nesta máquina (Windows 11 25H2 build 26200.9457). O protocolo não depende mais dele: usa `wsb start/connect/exec/stop` (CLI disponível desde 24H2). |
| Sandbox órfão (Server/RemoteSession vivos, sem janela) | o invoker atual encerra pelo ID com `wsb stop`; para órfão antigo, obtenha o ID com `wsb list --raw` e use `wsb stop --id ID` (nunca matar `vmwp` às cegas — WSL usa outro) |
| `sandbox: ja existe uma instancia ativa` | só um Sandbox por vez; feche a sessão existente. O invoker não encerra uma instância que não criou. |
| `.sandbox-job\` crescendo | jobs antigos não são apagados sozinhos → limpe a pasta de vez em quando |
| Sandbox não abre | recurso desabilitado ou sem virtualização → habilite Windows Sandbox + VT-x/AMD-V na BIOS |
| Clique deslocado no Sandbox | escala de DPI ≠ 100% no Sandbox — fixe 100% |
