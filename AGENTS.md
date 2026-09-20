# AGENTS.md — memória do projeto copilot-road-runner

> Arquivo de memória para agentes. Atualize ao mudar arquitetura, plano de
> testes ou descobrir quirk de plataforma. Idioma do repo: PT-BR.

## Direção vigente e ordem de leitura

- **Único plano vigente:** [docs/plano-agente-generico-2026-09-20.md](docs/plano-agente-generico-2026-09-20.md).
  Etapas **R0–R6 propostas, ainda não aprovadas**. Começar por R0; não continuar
  as antigas fases F0–F7. O plano de 19/09 foi removido: os status de conclusão
  não demonstravam funcionalidade end-to-end.
  Default atual **B1**; rollback explícito `--profile B0`. Não trocar default
  sem os gates novos. Matriz de 20/09 e revisão de 18/09 são históricas.
  Existência de contratos/testes offline não prova integração: há memória não
  enviada ao planner, done com evidência implícita e checkers a corrigir.
- Produto: computer use local, rápido, para GPU a partir de **6 GB de VRAM**;
  entender pedidos, observar monitores/janelas e usar mouse/teclado reais.
  UIA localiza e informa; modo GUI não usa edição semântica invisível ou open_url.
- Evoluir o código existente. Comparar perfil **duplo** (planner textual + visão)
  e **unificado** (VLM que planeja e enxerga), conforme gates do novo plano.
  Não fixar dois modelos como requisito futuro nem trocar default sem benchmark.
  A proibição de screenshots/coordenadas no planner vale para o papel textual;
  o perfil unificado deve usar contrato visual vinculado ao frame.
- Python observa/executa/veta; modelos escolhem ações, alvos, subobjetivos e skills.
  Memória de tarefa, IDs de observação/frame e confirmação de efeitos substituem
  heurísticas por app gradualmente, mantendo safety e testes durante a migração.
- Skills sob demanda podem habilitar CLI/scripts delimitados (ex.: Blender),
  explicitamente separados da GUI. Não habilitar shell arbitrário como fallback.
- `empero-ai/Qwen3.8-2B-Distill` é candidato comunitário experimental, não um
  Qwen3.8-2B oficial com visão validada. Conferir pesos/projetor e suporte antes
  de habilitá-lo como VLM; ver critérios de elegibilidade no plano vigente.
- Uso normal continua local, runtime próprio, sem flagship/API obrigatório.
  Testes dev com cliques continuam exclusivamente no Sandbox; exceções de
  hardware não cobertas exigem ambiente de teste dedicado, nunca o desktop de trabalho.

## Inventário atual (baseline; não representa os gates do novo plano)

- **Planner MiniCPM5-2B** (`:8091`, só texto, nunca recebe screenshot, nunca
  emite coordenadas) → **Vocaela-2** (`:8082`, screenshot → ação visual 0..1)
  → Python executa (tools, UIA, mouse/teclado) e NUNCA decide. (B0 = 1B fica
  como rollback via `--profile B0`.)
- Ordem: `open/focus/type` (planner) → `uia_click` por NOME → Vocaela
  (só quando o elemento não está na accessibility tree).
- Planner com `response_format: json_schema` (coordenadas impossíveis por
  construção); contexto UIA como `tipo:nome` (interativos primeiro);
  Vocaela recebe as últimas 3 ações como histórico.
- Runtime próprio (`server.py`), padrão e sem parâmetros: endpoints locais
  caídos → baixa llama.cpp + GGUFs p/ `models/` (gitignored, 1ª vez) e sobe
  `:8091`/`:8082` (portas fora do padrão: sem conflito com Ollama 11434 /
  LM Studio 1234; nenhuma dependência de `llama-server` externo);
  endpoint vivo é reusado, porta ocupada sem endpoint = erro honesto.
  `runtime.auto_start: false` ou `--no-runtime` desliga; URLs remotas
  (Sandbox → HOST_IP, só em testes dev) nunca baixam aqui.
  `uv run python -m server` deixa os dois no ar (`--host 0.0.0.0` só p/
  expor ao Sandbox em testes).
- Sem modelos online = erro honesto, sem fallback programático.
- Guard-rails determinísticos declarados (`loop.py`): bootstrap da janela do
  app ANTES do planner; anti-janela-errada e anti-repetição viram
  `last_error` p/ o planner; retries (`MAX_RETRIES=3`) NÃO consomem
  `max_steps`. `open_app` = whitelist (`tools.APP_COMMANDS`), nada passa por
  shell. Sem teleporte p/ URL (`open_url` removido): navegar é pela UI do
  navegador (ctrl+l, digitar, enter, cliques), como um humano.
- Revisão histórica: `docs/revisao-codebase-2026-09-18.md`.
  Roadmap vigente: `docs/plano-agente-generico-2026-09-20.md`.
- **UI opcional** (`main.py --ui`, extra `ui`: `uv sync --extra ui`): `app.py`
  = tray (pystray, thread daemon) + janela Spotlight (pywebview/WebView2,
  thread principal) + hotkey `ui.hotkey` (`ctrl+alt+space`) + agente em
  thread (janela se esconde antes de agir). `stt.py` = ditado ao vivo
  (faster-whisper `base` int8; parciais a cada 1 s, silêncio 1,5 s → final
  → `auto_send`). Lógica do ditado é pura (`Dictation.feed`) e testada sem
  mic/modelo. Erro do engine NUNCA vira instrução (`on_error`). Sandbox não
  instala a UI. Histórico de implementação: §10 do relatório; preservar durante
  a refatoração, mantendo STT inicialmente em CPU no orçamento de 6 GB.
- Arquivos-chave: `main.py` (CLI), `loop.py` (observe→decide→act→verify),
  `planner.py`, `vocaela.py`, `server.py` (runtime llama.cpp), `uia.py`,
  `actions.py`, `tools.py`, `safety.py`, `config.py`, `obs.py`.
- Módulos anteriores (integração a auditar em R0): `telemetry.py` + `evals/` (runner dry-run) +
  `runs/<id>/`; `schemas.py`/`state.py` (contratos, sem confidence fictícia);
  `verification.py` (efeito específico, done com evidências);
  `model_adapters.py` + `config.PROFILES` (B0..E2, unificado = 1 processo);
  `skills.py` + `skills/` (4 skills, CLI restrito); `http_pool.py` +
  `sequence` (≤3 primitivas). `--dry-run` bloqueia todos os efeitos.
- Perfil U1 executavel: `--profile U1` usa somente Qwen3-VL-2B-Instruct
  (GGUF Q4_K_M + mmproj F16) em um processo; o planner recebe screenshot em
  toda decisao e o mesmo endpoint faz grounding via `QwenGroundingAdapter`
  (JSON `{"x","y"}` 0..1, nunca `<Action>` do Vocaela). O runtime recusa
  checkpoint diferente, sem fallback silencioso para MiniCPM.

## Comandos

```powershell
uv run python -m unittest discover -s tests   # suite oficial (sempre via uv)
uv run ruff check                             # lint (dev-deps do pyproject)
uv run python main.py --self-test             # sem clicar em nada
uv run python main.py "..." --max-steps 4     # uso real: local, sem parâmetros
uv run python -m evals.runner --pilot --dry-run  # smoke, não valida tarefas
```

Use **uv** — o python do sistema não tem as deps (`pyautogui` etc.).
Sandbox: `.\scripts\Start-Sandbox.ps1` (uso manual, sem admin) e
`.\scripts\Invoke-SandboxTest.ps1 -Command '...' ` (eu rodo; com
`-Bootstrap` faz a bateria completa — 1ª vez demora minutos no winget).
Detalhes em `docs/sandbox-test-env.md`.

## Plano de teste = Windows Sandbox (só p/ testes dev; uso real é local)

Uso real: `uv run python main.py "..."` no host, sem parâmetros (runtime
próprio sobe os modelos sozinho). O Sandbox serve SÓ para testes dev com
cliques descartáveis, acionado apenas pelos scripts abaixo — nunca passar
`--config config.sandbox.json` no host (esse arquivo só existe dentro do
Sandbox, gerado pelo `bootstrap.ps1`).

Histórico: a VM Hyper-V (`crr-test`, scripts `New-TestVm/Reset-TestVm`)
foi removida em favor do Sandbox (commit `3e87285`) — menos setup manual,
cada abertura é um ambiente limpo descartável.

## Segurança (nunca relaxar)

- `pyautogui.FAILSAFE = True` (`actions.py`); hotkey `ctrl+alt+esc`
  (`safety.py`, configurável via `stop_hotkey`; ESC puro NÃO aborta — o
  agente usa `press_key esc`). Começar com `--max-steps 4`. Uso real roda
  no host (não use o PC enquanto age); testes dev com cliques vão no
  Sandbox.
- `type` usa `pywinauto.keyboard.send_keys` (Unicode); `pyautogui.typewrite`
  descarta acentos em silêncio no Windows.

## Quirks e correções históricas (não são backlog nem arquitetura obrigatória)

Preservar descobertas de plataforma/safety. Heurísticas de estratégia por app
abaixo são legado a substituir conforme o plano vigente, não regras a perpetuar.

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
- Overlay Tk nasce com título `tk` e pode estar em foreground: o planner via
  `tk`, copiava o exemplo do spec (`focus("trecho do título")`) e focava o
  próprio overlay → LOOP (run real 19/09). Janelas tituladas `crr-overlay`
  são ignoradas em `uia.snapshot` e `tools.focus` (`is_overlay_title`); exemplo
  do spec virou `Google` + regra anti-cópia no prompt; `focus` timeout 8s→3s.
- Run real 19/09 (rtx 5090 na amazon): o 1B copiou o exemplo `focus("Google")`
  e `focus_window` por substring casava QUALQUER aba do Chrome (todas terminam
  em "- Google Chrome") → falso sucesso + loop; `use_skill` GUI virava
  `wait(0ms)` executável → stall. Fixes: `tools.focus_window` casa na PARTE
  DA PÁGINA (`_page_part` stripa o sufixo; só nome de app — chrome/edge… —
  casa no título cheio) com ranking exato>prefixo>palavra; guarda anti-exemplo
  veta `focus("Google")` fora de pedido com "google"; bootstrap cobre
  chrome/edge/brave (`_browser_want`); skill GUI faz re-query com contexto em
  vez de placeholder; `sequence` rejeita passo misto press_key+keys.
- Run real 19/09 22:58 (amazon): ramo `sequence` em `_decide_planner` era
  inalcançável (`_planner_to_action` devolvia `wait(0)` antes) → open_app
  dentro de sequence executava placeholder sem validar; fix retorna None p/
  sequence. Bootstrap abria janela NOVA do Chrome → seletor de perfil
  ("Quem está usando?"); agora é focus-first (janela existente já está no
  perfil certo; adivinhar entre perfis é sensível). Dúvida honesta virou
  ação `ask` (human-in-the-loop, teto 3/run, timeout) + `prefs.json`
  (gitignored: ex. `browser_profile` lembrado após 1ª resposta).
- Run real 19/09 23:12 (amazon): 1B inventou `ctrl+alt+n` p/ nova aba
  (correta: `ctrl+t`) e repetiu 5x sem efeito. Fixes: receita de hotkeys no
  prompt/spec/skill (`ctrl+t` nova aba, `ctrl+l` endereço…); verify de
  sequence observa as combinações (`_verify_action`) e diz "no visible
  effect" + receita quando nada muda; `_repeat_note` cita o conteúdo da
  sequence; logs mostram `sequence(...)` em vez de `wait("")`.
- Runs reais 20/09 (rtx 5090, amazon "Continue shopping"): B1 avançou até
  `Amazon.com` e travou; U1 (174s, 4 vetos) nem saiu do step 1 com
  `planner_calls=0` no summary. Causas: (a) guarda browser-ativo dizia só
  "ctrl+l, type_text e enter" — na página da Amazon o certo é dispensar o
  intersticial via clique, não renavegar; (b) snapshot UIA do Chrome vinha
  com só 6 itens (Minimizar/Restaurar/Fechar/Nova guia/Window/Pane), sem
  conteúdo web — planner sem alvo redigitava URL; (c) `observe()` lia
  `hotkey(ctrl+l)` sem mudança de título como "wrong combo", quando tecla
  de foco NUNCA muda título; (d) `UNIFIED_SYSTEM` dizia só "same as textual"
  e o Qwen ignorou a regra de não-reabrir; (e) veto pós-planner descartava
  `tm`, escondendo custo/latência; (f) visão Qwen com system `<Action>` do
  Vocaela = protocolo errado (~40s p/ falhar em CPU). Fixes: guarda genérica
  (hotkey/type/uia_click/visual/sequence + "parte abrir CUMPRIDA" +
  intersticial primeiro); prompt §§1c/3b/3c + hint "page content NOT in UI
  elements → visual_action"; `observe()` neutro p/ teclas conhecidas
  (ctrl+l/ctrl+t/…); `UNIFIED_SYSTEM` = núcleo textual por extenso + frame
  0..1; `ctx._partial_tm` acumula custo no veto; `QwenGroundingAdapter`
  (JSON `{"x","y"}`) via `build_adapters` p/ modelo com "qwen" (Vocaela segue
  no B0/B1). U1 em CPU continua lento (~40s/chamada, binário CPU-only com
  `ngl=0`): sem GPU não há milagre; medir antes de trocar default (R3/R5).

## Workflow de git

- Commit + push a cada passo testável que valer (suite verde antes).
- Ignorados: `config.sandbox.json`, `sandbox/crr*.wsb`, `.sandbox-job/`,
  `last.png`, `run.jsonl`, `runs/`.
