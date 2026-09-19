# AGENTS.md — memória do projeto copilot-road-runner

> Arquivo de memória para agentes. Atualize ao mudar arquitetura, plano de
> testes ou descobrir quirk de plataforma. Idioma do repo: PT-BR.

## Arquitetura (2 modelos; Python executa/observa/veta, nunca escolhe)

- **Planner MiniCPM5-1B** (`:8091`, só texto, nunca recebe screenshot, nunca
  emite coordenadas) → **Vocaela-2** (`:8082`, screenshot → ação visual 0..1)
  → Python executa (tools, UIA, mouse/teclado) e NUNCA decide.
- Ordem: `open/focus/type` (planner) → `uia_click` por NOME → Vocaela
  (só quando o elemento não está na accessibility tree).
- Sem modelos online = erro honesto, sem fallback programático.
- Guard-rails determinísticos declarados (`loop.py`): bootstrap da janela do
  app ANTES do planner; anti-janela-errada e anti-repetição viram
  `last_error` p/ o planner; retries (`MAX_RETRIES=3`) NÃO consomem
  `max_steps`. `open_app` = whitelist (`tools.APP_COMMANDS`), `open_url` só
  http(s), nada passa por shell.
- Revisão completa + roadmap: `docs/revisao-codebase-2026-09-18.md`.
- Arquivos-chave: `main.py` (CLI), `loop.py` (observe→decide→act→verify),
  `planner.py`, `vocaela.py`, `uia.py`, `actions.py`, `tools.py`,
  `safety.py`, `config.py`, `obs.py`.

## Comandos

```powershell
uv run python -m unittest discover -s tests   # suite oficial (sempre via uv)
uv run ruff check                             # lint (dev-deps do pyproject)
uv run python main.py --self-test             # sem clicar em nada
uv run python main.py "..." --config config.sandbox.json --max-steps 4
```

Use **uv** — o python do sistema não tem as deps (`pyautogui` etc.).
Sandbox: `.\scripts\Start-Sandbox.ps1` (uso manual, sem admin) e
`.\scripts\Invoke-SandboxTest.ps1 -Command '...' ` (eu rodo; com
`-Bootstrap` faz a bateria completa — 1ª vez demora minutos no winget).
Detalhes em `docs/sandbox-test-env.md`.

## Plano de teste = Windows Sandbox (Hyper-V VM foi removida)

Histórico: a VM Hyper-V (`crr-test`, scripts `New-TestVm/Reset-TestVm`)
foi removida em favor do Sandbox (commit `3e87285`) — menos setup manual,
cada abertura é um ambiente limpo descartável.

## Segurança (nunca relaxar)

- `pyautogui.FAILSAFE = True` (`actions.py`); hotkey `ctrl+alt+esc`
  (`safety.py`, configurável via `stop_hotkey`; ESC puro NÃO aborta — o
  agente usa `press_key esc`). Começar com `--max-steps 4`. Nunca rodar
  cliques no host enquanto o usuário usa o PC — usar o Sandbox.
- `type` usa `pywinauto.keyboard.send_keys` (Unicode); `pyautogui.typewrite`
  descarta acentos em silêncio no Windows.

## Quirks descobertos (não redescobrir)

- Shell das ferramentas = **PowerShell 5.1**: sem `head`/`&&`; usar
  `Select-Object`, `;` ou `; if ($?) { }`.
- `Start-Process powershell -PassThru` + `.ExitCode` **não é confiável**
  (vem vazio) → `sandbox/agent.ps1` usa wrapper com `$LASTEXITCODE`
  em modo estrito (`$ErrorActionPreference='Stop'`).
- Em here-string `@" "@`, `$` expande: escapar como `` `$ `` ao gerar
  scripts (foi o bug do `$ErrorActionPreference` no wrapper).
- `[void][xml]$x = ...` é sintaxe inválida; usar `$x = [xml]...`.
- PS 5.1: `Get-Content -Raw` **não aceita wildcard**; `-File` com
  `-Command '...'` (aspas simples) para `$env:` não expandir no host.
- Host alcança modelos em `127.0.0.1:8091/8082`; no Sandbox o host é o
  **gateway** (`HOST_IP`, preenchido pelo `bootstrap.ps1`).
- `Invoke-SandboxTest.ps1` fecha em `finally` pelo ID com `wsb stop`
  (timeout não deixa órfão); jobs ficam em `.sandbox-job\` (gitignored).
  Histórico: matar só `WindowsSandboxClient` deixou Server/RemoteSession
  órfãos em 18/09. Para instância antiga use `wsb list --raw` +
  `wsb stop --id ID`; nunca matar `vmwp` às cegas — WSL usa outro.
- `LogonCommand` do `.wsb` NÃO dispara nesta máquina (Windows 11 Pro 25H2
  build 26200.9457; confirmado manual em 18/09). Não depender dele:
  `Start-Sandbox.ps1` e `Invoke-SandboxTest.ps1` usam a CLI oficial
  `wsb start/connect/exec -r ExistingLogin/stop`. Smoke test do ciclo
  completo passou. Só um Sandbox por vez; os scripts recusam iniciar se
  já houver uma instância, e encerram pelo ID apenas a que criaram.
- `wsb exec` não retorna stdout (só `{"ExitCode": 0}`) → observabilidade
  do agente é por arquivos em `C:\job\out`. E `cmd /c start "" ...` com
  título vazio morre em silêncio sob `wsb exec` (ExitCode 0, nenhum
  marker): o dispatch usa `start` SEM título vazio (provado T1-T5 em
  18/09: mapping ok, ps direto ok, agent foreground ok, detach sem
  título ok).
- Arquivos `.py` já entraram com UTF-8 duplo + BOM (mojibake no prompt do
  planner); `test_cleanup.test_sem_mojibake_nem_bom` trava. `.editorconfig`
  + `.gitattributes` fixam UTF-8/LF (`.ps1` CRLF).
- `mss.monitors[0]` é o desktop VIRTUAL (left/top podem ser negativos);
  `obs.crop_to_rect` converte tela↔pixel. `uv sync` dentro do Sandbox usa
  `UV_PROJECT_ENVIRONMENT` fora de `C:\crr` (senão sobrescreve o `.venv` do host).
- Timeouts das ferramentas em ms; trial no Sandbox leva ~1 min
  (sem `-Bootstrap`).

## Workflow de git

- Commit + push a cada passo testável que valer (suite verde antes).
- Ignorados: `config.sandbox.json`, `sandbox/crr*.wsb`, `.sandbox-job/`,
  `last.png`, `run.jsonl`.
