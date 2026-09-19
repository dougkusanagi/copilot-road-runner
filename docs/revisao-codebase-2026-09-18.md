# Revisão da base de código e do plano — 18/09/2026

> Escopo: todos os `.py` da raiz (12 arquivos, ~2.000 linhas), os 4 arquivos de
> teste, os scripts PowerShell do Sandbox, `AGENTS.md`, `README.md`,
> `docs/sandbox-test-env.md`, `pyproject.toml`/`uv.lock` e `.gitignore`.
> Evidências coletadas: leitura integral, `uv run python -m unittest discover -s tests -v`
> (58 testes, verde, 2,2 s), `git log`, inspeção de encoding dos arquivos.
> Nada foi alterado além deste documento.

## 1. Resumo executivo

O projeto está num bom estado para um MVP de 26 commits em um dia: a divisão
planner (texto) → UIA → Vocaela (visão) → executor é clara, cada arquivo tem uma
responsabilidade só, a suite offline roda em 2 s sem GUI nem modelos, e os
quirks de plataforma descobertos estão documentados em `AGENTS.md` — isso
economiza horas. O plano de teste com Windows Sandbox via `wsb.exe` é a decisão
certa e já tem smoke test.

Dito isso, a revisão encontrou **7 defeitos que afetam o comportamento em
produção** (não só estilo) e que a suite atual não pega, porque ela cobre
parsers/config/docs mas quase nada do caminho `loop.run → actions.execute →
obs`:

| # | Defeito | Onde | Impacto |
|---|---|---|---|
| 1 | Prompt do planner contém **mojibake** (`â€”`, `VISÃVEL`, `NÃƒO`, `botÃ£o`) — arquivos gravados com UTF-8 duplo + BOM | `planner.py` (`TOOLS_SPEC`, docstrings), `main.py`, `config.py`, `tests/test_two_models.py` | Tokens-lixo em toda chamada ao modelo 1B; `--help` e mensagens ao usuário ilegíveis; teste `test_decision_valida` passa por acidente comparando lixo com lixo |
| 2 | `.venv` do Sandbox e do host **colidem** (`uv sync` em `C:\crr` = pasta mapeada do repo) | `sandbox/bootstrap.ps1` | Cada boot do Sandbox recria o `.venv` do host com Python 3.12 de outra máquina; host recria de volta; risco de lock/corrupção enquanto os dois rodam |
| 3 | Crop da janela ativa usa coordenadas de tela sobre uma imagem cujo (0,0) é o canto do **desktop virtual** (`monitors[0]`, pode ser negativo) | `obs.capture_for_vision`, `_foreground_rect` | Em multi-monitor com monitor à esquerda/acima do primário, o Vocaela vê a região errada e o clique cai deslocado |
| 4 | `pyautogui.typewrite` **descarta caracteres não-ASCII** silenciosamente (só mapeia 32..127 no Windows) | `actions.execute` (`type`) | "Olá, não" vira "Ol, no" — sério para um repo PT-BR |
| 5 | Overlay azul fica **órfão** quando o planner está offline (retorno antecipado só chama `safety.stop()`) | `loop.run` | Borda "este computador está sendo controlado" permanece após o programa sair |
| 6 | Comando do planner vai para `shell=True` sem whitelist | `tools.open_app`, `tools.open_url` | Superfície de injeção: um `app` ou `url` com `&`, `"` ou `%` vira comando de `cmd` — o planner lê texto de tela (páginas web) e pode ser induzido |
| 7 | `presses > 1` do Vocaela é descartado; `MIDDLE_CLICK` vira `click`; `scroll left/right` vira vertical | `vocaela._normalize`, `visual_to_action`, `actions.execute` | Ações executadas diferem do que o modelo pediu, sem log |

Além desses, há **tensão entre o plano declarado e o código**: `AGENTS.md`/`loop.py`
dizem "decisão 100% por IA, sem router determinístico", mas `_app_bootstrap`, a
guarda `CALC_WORDS` e três extractors por regex (`_extract_text_to_type`,
`_extract_digit`, `_extract_search_query`, os três mortos) são exatamente um
router por palavra-chave. Não é errado ter guard-rails — é errado não declará-los.
Ver §5.

Ordem sugerida de ataque: §2 (correções) → §6.1 (tooling: 1 h, evita regressão
do item 1 e do encoding) → §5.2 (verify com feedback ao planner) → §7 (harness
de avaliação no Sandbox).

## 2. Correções (bugs)

### 2.1 P0 — afetam resultado em produção

**C1. Mojibake + BOM em 4 arquivos.**
`planner.py`, `main.py`, `config.py` e `tests/test_two_models.py` começam com
BOM (`EF BB BF`) e têm o texto PT-BR codificado duas vezes. O pior efeito está em
`TOOLS_SPEC`/`PLANNER_SYSTEM`, que vão em **toda** requisição ao MiniCPM:

```
- {"type":"uia_click","target":"nome do elemento"} â€” clicar elemento VISÃVEL na Ã¡rvore ...
- {"type":"visual_action", ...} â€” SÃ“ quando o elemento NÃƒO estÃ¡ ...
```

Um modelo de 1B com temperatura 0,1 é sensível a ruído no system prompt.
Correção mecânica (uma vez): `s.encode("cp1252").decode("utf-8")` sobre o
conteúdo e gravar sem BOM. Prevenção: `.editorconfig` (`charset = utf-8`,
`end_of_line = lf`) + `.gitattributes` (`*.py text eol=lf`) + um teste que
falha se algum `.py` contiver `Ã` ou `â€` ou começar com BOM (está no espírito
de `test_cleanup.py`). Corrigir também as asserções `"OlÃ¡"` no teste.

**C2. `uv sync` do Sandbox escreve no `.venv` do host.**
`bootstrap.ps1` faz `Set-Location C:\crr; uv sync`, e `C:\crr` é o repo mapeado
com `ReadOnly=false`. Correção: antes do `uv sync`,
`$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\crr-venv"` (fica dentro do
Sandbox, descartado no fim) e opcionalmente `$env:UV_CACHE_DIR` apontando para
uma segunda pasta mapeada só de cache, para não baixar as wheels a cada boot.
Bônus: mapear o repo como `ReadOnly=true` no `.wsb` do launcher (`Start-Sandbox.ps1`)
já que só o job precisa escrever, e o job já tem `C:\job`. Nota: `config.sandbox.json`
é gravado em `C:\crr` pelo bootstrap; com read-only teria de ir para `C:\job`
ou ser passado via `--planner-url/--vision-url` (já existem).

**C3. Offset do desktop virtual ignorado em `obs.capture_for_vision`.**
`sct.monitors[0]` é a caixa envolvente de todos os monitores (o docstring diz
"monitor primário", está errado). O pixel (0,0) da imagem corresponde a
`(monitors[0]["left"], monitors[0]["top"])`, que é negativo se houver monitor à
esquerda/acima. `_foreground_rect` devolve coordenadas de tela; o `crop` usa
essas coordenadas direto, e `l = max(0, l)` ainda corta janelas legitimamente em
x negativo. Correção: `l -= mon["left"]; t -= mon["top"]` antes do crop e
devolver `origin` em coordenadas de tela (somar de volta). Cobrir com teste
unitário injetando `monitors[0] = {"left": -1920, ...}`. `overlay.py` já trata
esse caso — o conhecimento existe no repo, só não foi aplicado aqui.
Relacionado: chamar `ctypes.windll.shcore.SetProcessDpiAwareness(2)` no início
de `main.py` (antes de importar pywinauto/pyautogui) para que `GetWindowRect`,
`mss` e `pyautogui` falem a mesma unidade em DPI ≠ 100 %.

**C4. `type` com texto não-ASCII.**
`pyautogui.typewrite`/`write` no Windows só tem mapeamento para ASCII 32..127;
o resto é ignorado sem erro. Trocar por `pywinauto.keyboard.send_keys(text,
with_spaces=True, with_newlines=True)` (usa `SendInput` Unicode; pywinauto já
é dependência) — escapando `{}+^%~()` — ou colar via clipboard (`ctrl+v`) para
textos longos. Teste: mockar `pyautogui`/`send_keys` e afirmar que "Olá" chega
inteiro.

**C5. Overlay órfão no retorno `no_model`.**
Em `loop.run`, o overlay sobe **antes** de checar o planner; o `return` do ramo
offline chama `safety.stop()` mas não `overlay.stop()`. Correção mínima: mover a
subida do overlay para depois dos dois `check()`; ou envolver tudo no `try/finally`
que já existe.

**C6. Planner → shell sem whitelist.**
`tools.open_app`: qualquer `app` fora de `APP_COMMANDS` e sem `.exe` vira
`cmd /c start "" {target}` com `shell=True`. `tools.open_url` monta
`cmd /c start "" "{url}"` — uma aspa dupla na URL sai da citação. Correção:
`open_app` recusa alvo fora do dicionário (erro honesto → vira `last_error`
para o planner, coerente com a filosofia do projeto); `open_url` usa
`os.startfile(url)` após validar `urlparse(url).scheme in ("http", "https")`.
Sem `shell=True` em nenhum lugar.

**C7. Semântica perdida no caminho Vocaela → executor.**
- `_normalize`, ramo `key`: `"+".join([kw["key"]] * 1)` é no-op e `presses`
  vai para `text`, que `actions.execute("hotkey")` ignora. Adicionar
  `Action.clicks`/`presses` ou repetir no executor.
- `MIDDLE_CLICK → click`: mapear para um tipo próprio ou recusar honestamente.
- `SCROLL left/right`: `pyautogui.hscroll` existe; hoje vira scroll vertical.
- `ANSWER`: o texto da resposta é jogado fora; ao menos logar em `run.jsonl`
  e devolver ao planner como `last_error`/observação.
- Só a primeira ação do array é usada; as demais são descartadas em silêncio.
  Logar `dropped=N` no timing e considerar executar sequências curtas
  (`click` + `type` é o caso comum).

### 2.2 P1 — comportamento errado, mas contido

**C8. `n` sombreado em `loop.run`.** `emit()` usa `nonlocal n` como contador de
linhas; o `except RuntimeError` faz `n = ctx.get("decide_errors", 0) + 1`, que é
a **mesma** variável. Após um retry, a numeração `[n]` do console reinicia em 1–3.
Renomear para `retries`.

**C9. `forced_vision` não força nada.** Ao detectar a mesma ação 3×, o loop marca
`forced_vision = True`, limpa `history` e `continue` — mas `decide()` nunca lê
essa flag. Efeito real: pula um step (gasta 1 de `max_steps`) e imprime uma
mensagem falsa. Ou passar a intenção ao planner via `last_error`
("você repetiu X 3 vezes; escolha outra ação") — o que mantém a decisão no modelo —
ou remover.

**C10. Planner é chamado e a resposta é descartada pelo bootstrap.** Em
`_decide_planner`, `planner.next_action()` roda **antes** de `_app_bootstrap`;
se o bootstrap decidir, a decisão do modelo é jogada fora (paga-se a latência do
1B à toa, nos 1–2 primeiros steps). Inverter a ordem.

**C11. Retry consome `max_steps`.** Erro de decisão → `continue` no `for step in
range(max_steps)`; com `--max-steps 4` (o padrão recomendado), 3 retries deixam
1 step útil. Contar retries fora do orçamento de steps, ou reportar `steps` e
`retries` separados no summary (hoje `summary["steps"]` já ignora os retries,
mas o orçamento não).

**C12. `no_vision` incoerente.** `cfg["no_vision"]` é lido em dois lugares, mas
se o planner pedir `visual_action` o Vocaela é chamado mesmo assim e falha.
Ou remover a opção (não documentada) ou fazer `decide` devolver `last_error`
("visão desabilitada; use uia_click/teclado").

**C13. Duplicações e sobras em `loop.run`:** `vocaela.check()` chamado duas
vezes (`vs`, `vs2`); `mode` sempre `"planner"`; `tm.get("tool_ms")` nunca é
preenchido; `Decision.confidence` é constante (1.0/0.9/0.8) e não carrega
informação — remover ou derivar de algo real (ex.: exact/prefix/sub do
`_resolve_uia`).

**C14. ESC puro aborta o run.** `safety._watch` aborta em `is_pressed("esc")`.
Isso significa que (a) o usuário fechar um diálogo com ESC dentro do Sandbox
mata a bateria e (b) o próprio agente executando `press_key: esc` (permitido em
`TOOLS_SPEC`) pode se auto-abortar (corrida com o poller de 100 ms; não é
determinístico, mas acontece). Manter só `ctrl+alt+esc` (que já tem
`add_hotkey`) e alinhar o README, que ainda anuncia "Pressione ESC".
`config["stop_hotkey"]` existe mas `safety.HOTKEY` é hardcoded — ligar os dois.

**C15. Sockets abertos nos testes.** `_make_server` em `test_two_models.py`
chama `srv.shutdown()` mas não `srv.server_close()` → `ResourceWarning` a cada
run. Trivial, mas polui a saída e esconde warnings reais.

### 2.3 P2 — pequenos

- `planner.PlannerDecision._no_coords_type` é um validator vazio; `assert_no_coords`
  faz o trabalho de verdade. Remover o primeiro ou mover a checagem para um
  `model_validator(mode="before")`, assim `model_validate(raw)` já recusa.
- `vocaela.VocaelaAdapter.act` (async) anota `-> VisualAction` mas devolve a
  tupla `(VisualAction, ms)`.
- `obs.take_screenshot` recebe `max_width`/`jpeg_quality` e ignora ambos.
- `uia.py` e `tools.py` importam `pywinauto.Desktop` dentro de funções
  repetidamente e criam um `Desktop(backend="uia")` por chamada; cachear um
  módulo-level é seguro e economiza COM init.
- `actions.execute` usa `assert` para validar entrada; `python -O` remove.
  Trocar por `if ...: raise ValueError`. O `except (ValueError, AssertionError)`
  em `loop.run` então fica só `ValueError`.
- `agent.ps1`: se `bootstrap.ps1` lançar (winget falhou, sem rede), com
  `$ErrorActionPreference="Stop"` o agente morre **sem** gravar `exitcode.txt`
  nem `done.marker`; o host só vê "timeout após 900 s". Envolver em `try/catch`
  que grava `exitcode.txt=125` + `stderr.log` + `done.marker`.
- `Invoke-SandboxTest.ps1` não repassa `-JobTimeoutSec`; o agente usa 1200 s
  enquanto o host espera `-TimeoutSec` (900 s por padrão). Passar
  `-JobTimeoutSec ($TimeoutSec - 30)` para que o job morra com 124 **antes** do
  host desistir e o resultado parcial seja lido.
- `Invoke-SandboxTest.ps1` com `-OpenModelPorts` sem admin faz `return` **depois**
  de criar `.sandbox-job\<id>` → pasta órfã. Checar elevação antes de criar o job.
- `wsb start --config $xml` recebe o **conteúdo** XML, não o caminho; o arquivo
  `crr-agent.local.wsb` gravado logo antes serve só para inspeção. Comentar
  isso ou passar o caminho, para não confundir quem lê.

## 3. Código morto e limpeza

`test_cleanup.py` trava a remoção da era anterior, mas sobraram restos da era
atual:

| Símbolo | Arquivo | Estado |
|---|---|---|
| `_extract_text_to_type`, `_extract_digit`, `_extract_search_query`, `_has_any` (só usado pela guarda calc) | `loop.py` | nunca chamados |
| `foreground_title` | importado em `loop.py` | não usado (o comentário diz "guard calc", mas a guarda usa `title` do snapshot) |
| `snapshot()`, `find_window_titles()` | `uia.py` | só `__main__` / via `tools.list_windows`, que ninguém chama |
| `click_element`, `type_text`, `press`, `press_key`, `hotkey`, `wait`, `list_windows`, `TOOLS` | `tools.py` | registry "p/ planner futuro" — o planner atual não usa; `loop._planner_to_action` reimplementa o mapeamento |
| `UIElement.center`, `Observation` | `schemas.py` | sem uso fora de `uia.snapshot` |
| `--lmstudio-url` | `main.py` | marcado deprecated no mesmo dia em que nasceu |
| `_MockState` | `tests/test_two_models.py` | classe vazia |
| `ctx["planner_errors"]` | `loop.py` | escrito, nunca lido |

Sugestão: um commit "Cleanup: era 2 modelos" que remove tudo acima e estende
`test_cleanup.DEAD_MODULES`/uma lista `DEAD_SYMBOLS`. `uia.py` fica só com
`active_window_snapshot` (+ um walker reutilizável), `tools.py` só com
`open_app`, `open_url`, `focus_window`.

Também há duplicação real: a construção de `VocaelaAdapter`/`MiniCPMPlanner` a
partir de `cfg` aparece em `main.locate_only` e em `loop.run` (e o
`--self-test` não valida `cfg`). Um `config.py: build_planner(cfg)`,
`build_vision(cfg)` — ou melhor, um `Config` pydantic (pydantic já é dependência)
com `PlannerCfg`, `VisionCfg`, defaults e validação de URL/timeouts — substitui
`DEFAULTS` + merge raso + `.get(..., default)` espalhado em 6 lugares.

## 4. Plano de teste (Windows Sandbox) — revisão

O que está bem: uso da CLI `wsb` em vez de `LogonCommand` (regressão confirmada
e documentada), encerramento pelo ID no `finally`, heartbeat `started.marker`,
exit code via `$LASTEXITCODE` em wrapper estrito, recusa de segunda instância,
e testes que parseiam os `.ps1` com o parser oficial sem executar. O protocolo
por pasta mapeada é simples e observável.

Pontos a corrigir/decidir (além de C2 e dos itens P2 acima):

1. **Docstrings desatualizadas.** `agent.ps1` e `bootstrap.ps1` ainda dizem
   "via LogonCommand do .wsb" no `.SYNOPSIS`; `agent.ps1` comenta "prova que o
   LogonCommand rodou". `AGENTS.md` já diz o contrário. Atualizar (é o tipo de
   coisa que `test_sandbox_plan` poderia travar: `assertNotIn("LogonCommand", AGENT)`).
2. **Custo por boot.** winget + `uv sync` a cada abertura (minutos). Opções, em
   ordem de esforço: (a) `UV_CACHE_DIR` numa pasta mapeada persistente;
   (b) baixar o instalador embeddable do Python + binário `uv` uma vez para
   `sandbox/cache/` (gitignored) e copiar em vez de winget; (c) manter uma
   pasta mapeada `tools/` já com `.venv` pré-construído para 3.12 x64
   (o Sandbox é sempre a mesma imagem, então um venv construído lá é reutilizável).
3. **Paridade de Python.** Host resolveu **3.14.6** (não há `.python-version`;
   `requires-python >= 3.12`); o Sandbox instala 3.12. Bugs de `pywinauto`/
   `keyboard`/`pyautogui` podem aparecer só em um dos lados. Pinar
   `.python-version` = `3.12` e deixar o bootstrap ler a mesma versão.
4. **Só um Sandbox por vez + `-KeepOpen`** = um `-KeepOpen` esquecido bloqueia
   toda a bateria seguinte com uma mensagem genérica. Sugestão: `-KeepOpen`
   grava `.sandbox-job\current.id`; o próximo `Invoke-SandboxTest` oferece
   `-Reuse` (roda no mesmo Sandbox, sem novo bootstrap — grande ganho de tempo)
   ou `-Force` (para o antigo pelo ID salvo).
5. **`.sandbox-job` cresce sem limite** (a doc admite). `-Prune 10` ou limpeza
   automática dos jobs mais antigos que N no início do invoker.
6. **O plano não define o que é "verde".** Há infraestrutura para rodar
   *qualquer* comando, mas não há uma bateria canônica de tarefas end-to-end
   nem um critério de sucesso verificável. Ver §7.
7. **DPI no Sandbox**: a doc pede "fixe 100 %" manualmente; o bootstrap pode
   fazê-lo (`HKCU\Control Panel\Desktop\LogPixels=96`, `Win8DpiScaling=1`, requer
   logoff) — ou, mais simples, C3 + `SetProcessDpiAwareness` tornam isso irrelevante.
8. **Rede**: a doc manda subir `llama-server --host 0.0.0.0`, expondo os modelos
   na LAN. Preferir `--host <IP do adaptador do Sandbox/vEthernet>` ou restringir
   a regra de firewall `crr-model-*` a `-RemoteAddress` da sub-rede do Sandbox
   (`172.x`/`192.168.x` da vEthernet). Pequeno, mas o script cria regras
   permanentes no host.

## 5. Arquitetura e plano — pontos de tensão e propostas

### 5.1 "100 % IA" vs guard-rails determinísticos

`_app_bootstrap` (regex notepad/calc), a guarda `CALC_WORDS` e o anti-loop são
decisões determinísticas que **sobrepõem** o planner. Elas existem por bons
motivos (um 1B não abre processo; janela errada é o modo de falha nº 1). O
problema é que estão apresentadas como exceções envergonhadas, hardcoded para
dois apps, e não generalizam (Edge não tem bootstrap; qualquer outro app também não).

Proposta: declarar explicitamente uma camada **"guards"** (Python pode *vetar* e
*observar*; nunca *escolher*), com regras genéricas em vez de por app:

- **Pré-condição de foco**: se a última ação foi `open_app X` e o título da janela
  ativa não mudou após `verify`, devolver `last_error` ao planner — sem regex na
  instrução do usuário. Isso substitui a guarda calc para qualquer app.
- **Veto de repetição**: "mesma ação 3×" vira `last_error` estruturado para o
  planner, não um `continue` mudo (resolve C9 no espírito do projeto).
- **Veto de coordenada/janela**: já existe (`_check_coords`, `wrect`). Só documentar.

E documentar isso em `AGENTS.md` como "Python veta e observa; nunca escolhe" —
frase mais honesta que "100 % IA" e ainda fiel à intenção.

### 5.2 `verify` não devolve nada útil ao planner

Hoje `verify()` só dorme e lê o título. O planner decide o próximo passo com
`goal + título + 40 nomes + 5 labels de histórico`, sem saber se a ação anterior
**funcionou**. Para um 1B, isso é a diferença entre convergir em 4 steps ou
alucinar `done`. Observações baratas, sem modelo, já disponíveis via UIA:

- título antes/depois da ação (mudou? era o esperado?);
- para `type`: valor do controle `Edit`/`Document` focado contém o texto?
  (pywinauto `.get_value()`/`legacy_properties().Value`);
- para `uia_click`: o alvo existia (hit exact/prefix/sub) e desapareceu/mudou de
  estado (`toggle_state`, `is_selected`)?;
- para `open_app`: PID novo + janela top-level nova.

Mandar isso como `Result of last action: ...` no prompt. Isso também é a base
para um `done` honesto (§5.3) e para o harness (§7).

### 5.3 `done` sem confirmação

O planner pode dizer `done` a qualquer momento e o loop aceita. Duas opções
compatíveis com a filosofia:

- (barata) exigir que `done` só seja aceito se `hist_labels` tiver ≥ 1 ação
  não-`wait`; caso contrário devolver `last_error` "nada foi feito ainda";
- (melhor) segunda chamada curta ao planner com a observação do §5.2:
  "Goal / Observed state / Answer yes|no: is the goal complete?" — ainda é o
  modelo decidindo, mas com evidência.

### 5.4 Saída estruturada em vez de regex

`llama-server` aceita `response_format: {"type": "json_schema", "json_schema": {...}}`
(ou `grammar` GBNF) e **garante** JSON válido conforme o schema — inclusive
restringindo `type` ao `Literal` e proibindo `x`/`y` por construção
(`additionalProperties: false`). Gerar o schema com
`PlannerDecision.model_json_schema()` e enviá-lo elimina `extract_json`,
`assert_no_coords` e a classe de erro "planner não retornou JSON válido" (que
hoje custa retries e steps). Mesmo para Vocaela é possível forçar a
estrutura do array dentro de `<Action>`, embora aí o formato oficial já seja
estável. Referência: <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
(seção *POST /v1/chat/completions*, campos `response_format` / `json_schema`).

### 5.5 Contexto dado ao planner é pobre

- `ui_names` = 40 **primeiros** nomes em ordem de árvore, profundidade ≤ 6. No
  Edge isso é quase só chrome (abas, toolbar); o conteúdo web fica fora. Enviar
  `tipo:nome` (`Button:7`, `Edit:Pesquisar`, `Hyperlink:Comprar`) e priorizar
  controles interativos (Button/Edit/Hyperlink/MenuItem/ListItem/TabItem) antes
  de Text/Group.
- `MAX_DEPTH=6` + `children()` recursivo (uma chamada COM por nó) é lento
  (o timeout de 5 s por step é sintoma). `descendants(depth=...)` do pywinauto,
  ou um `TreeWalker` com `CacheRequest`, reduz muito a latência e permite subir a
  profundidade.
- Vocaela: o system prompt oficial fala em "action history sequence", e o
  adapter não envia histórico. Enviar as últimas 2–3 ações visuais como texto
  antes da instrução é barato e é o que o modelo viu em treino.
- O planner recebe `hist_labels` em PT/EN misturado (`click(30,30)`,
  `visual "Click X" -> click(0.5,0.4)`). Padronizar labels curtos e sem
  coordenadas absolutas (o planner "não vê a tela", mas recebe pixels no
  histórico).

### 5.6 Robustez de rede

- Um `httpx.Client` **por chamada** (planner e Vocaela): sem keep-alive; criar um
  `Client` por adapter e reutilizar.
- Sem retry/backoff para 5xx/timeout do `llama-server` (que ocorrem quando o
  slot está ocupado). 1–2 tentativas com backoff curto no adapter, antes de virar
  `RuntimeError` para o loop.
- `timeout_s=90` para um 1B: se o servidor travar, um step leva 90 s. 20–30 s é
  mais realista; medir com o harness.

## 6. Adições sugeridas

### 6.1 Tooling (baixo esforço, alto retorno)

| Item | Motivo |
|---|---|
| `[dependency-groups] dev = ["ruff", "pytest"?]` no `pyproject.toml` | `[tool.ruff]` está configurado mas `uv run ruff` falha ("program not found"). Hoje não há lint nenhum — C1 e o código morto do §3 seriam pegos por `ruff check` (F401/F841) |
| `.python-version` = `3.12` | paridade host/Sandbox (§4.3) |
| `.editorconfig` + `.gitattributes` (`* text=auto eol=lf`, `*.ps1 eol=crlf`) | mistura CRLF (`.py` da raiz, `test_two_models.py`) e LF (outros testes, docs, scripts); previne recorrência de C1 |
| `LICENSE` | o repo é **público** e não tem licença → juridicamente "todos os direitos reservados", ninguém pode usar |
| GitHub Actions `windows-latest`: `uv sync --frozen` + `uv run ruff check` + `uv run python -m unittest discover -s tests` | a suite é offline e roda em 2 s; PowerShell existe no runner (o `ParseFile` test passa). Sem Sandbox no CI, mas trava regressão do resto |
| `uv run python -X dev -m unittest` no CI | transforma `ResourceWarning` (C15) em sinal visível |
| Type check (`pyright`/`mypy --strict` só em `schemas/planner/vocaela`) | pegaria C7 (`act` anota tipo errado) e `Action` opcionais usados sem checagem |

### 6.2 Observabilidade

- Diretório por run (`runs/<timestamp>/`): `run.jsonl`, `step-NN.png` (o que o
  Vocaela viu), `planner-NN.txt` (prompt **e** resposta bruta), `summary.json`.
  Hoje `run.jsonl` é apagado a cada run e o prompt do planner nunca é gravado —
  não dá para depurar "por que ele escolheu isso". `.gitignore` já tem `run-*/`,
  sinal de que foi planejado.
- `--dry-run`: roda o loop imprimindo as decisões sem `execute` (só `open`/`focus`
  vetados). Útil para testar prompts sem Sandbox.
- `--replay runs/X/`: reenvia os prompts gravados ao planner para comparar
  versões de prompt/modelo (A/B offline).

### 6.3 Documentação

- README ainda diz "Pressione **ESC** para abortar" (vs `ctrl+alt+esc` em
  `AGENTS.md`/`safety.py`), e não explica **como subir os dois `llama-server`**
  (nome dos GGUF, `--mmproj` do Vocaela, `-ngl`, `--host`, `--port 8091/8082`,
  `-c`). Uma seção "Modelos" com os dois comandos completos é o maior gap para
  alguém clonar e rodar.
- `docs/arquitetura.md` curto (o que está no topo de `loop.py`/`AGENTS.md`),
  com o diagrama do fluxo e a lista explícita de guard-rails (§5.1).
- `CHANGELOG.md` ou tags: os commits `E1/E2/E3/F1..F4` são marcos, mas só estão
  no `git log`.
- Sincronizar `.SYNOPSIS` dos `.ps1` (§4.1).

## 7. Harness de avaliação (a adição mais valiosa)

O projeto tem tudo para medir progresso de forma objetiva e ainda não mede.
Proposta mínima, dentro do que já existe:

1. `evals/tasks.json`: 6–10 tarefas canônicas com **checker UIA** determinístico:
   - Notepad: "escreva Hello World" → `Document.value == "Hello World"`;
   - Calculadora: "7 + 8 =" → `Text CalculatorResults` contém `15`;
   - Edge: "abra example.com" → título contém `Example Domain`;
   - Notepad: texto com acentos ("Olá, não") — pega C4;
   - tarefa com elemento sem nome acessível (força Vocaela);
   - tarefa impossível ("clique no botão roxo inexistente") → esperado `stuck`
     em ≤ N steps, não `done`.
2. `evals/run.py`: roda cada tarefa K vezes via `loop.run`, aplica o checker,
   grava `evals/results/<ts>.json` com `success`, `steps`, `planner_calls`,
   `vocaela_calls`, `avg_planner_ms`, `avg_vision_ms`, `result`.
3. `Invoke-SandboxTest.ps1 -Bootstrap -Command "uv run python evals/run.py"`
   como "bateria completa" oficial no `AGENTS.md`.
4. Métrica-alvo no README: taxa de sucesso e latência média por tarefa; cada
   mudança de prompt/modelo (ex.: §5.4, §5.5) vem com o antes/depois.

## 8. Lacunas de teste

A suite atual é boa em parsers, config e "o doc menciona X". Não cobre:

| Área | O que testar (offline, com fakes/mocks) |
|---|---|
| `loop.run` | com `_FakePlanner` sequencial + `execute` mockado: `done` encerra; retry 3× → `stuck`; anti-loop; `max_steps`; overlay/safety parados no `finally` **e** no ramo `no_model` (C5); `n`/retries (C8) |
| `actions.execute` | `pyautogui` mockado: mapeamento de cada `Action.type`; `_check_coords` recusa; texto não-ASCII (C4); `presses`/`clicks` |
| `obs.capture_for_vision` | `mss` mockado com `monitors[0].left = -1920`: crop e `origin` corretos (C3) |
| `tools.open_app/open_url` | alvo fora da whitelist é recusado; URL com `"`/`&` não vira comando (C6) |
| `vocaela._normalize` | `presses>1`, `MIDDLE_CLICK`, `scroll left`, array com 2 ações (C7) |
| `planner` | prompt sem mojibake/BOM (C1); `json_schema` presente no payload (§5.4) |
| `safety` | `HOTKEY` vem de `cfg["stop_hotkey"]`; ESC puro **não** aborta (C14) |
| `_resolve_uia` | empate exact vs prefix, `len(name) > 60`, dígito↔palavra PT/EN (só há 3 casos hoje) |
| Sandbox | `agent.ps1` grava `done.marker` mesmo se bootstrap falhar (P2); `-JobTimeoutSec` repassado |

Observação: os testes de `test_sandbox_plan.py`/`test_cleanup.py` que fazem
`assertIn("trecho", src)` são úteis como trava de documentação, mas são
frágeis a refactor de texto e não testam comportamento; não crescer nessa
direção — o `ParseFile` do PowerShell e o `_render_wsb` → XML são o modelo certo.

## 9. Roadmap priorizado

> **Status (18/09, mesmo dia):** P0 C1–C7 e P1 C8–C15 implementados e commitados
> (`5f55188`, `f0e843d`, `0b2b2b8`, `b09424f`) — 77 testes, `ruff` limpo, CI Windows.
> Também feitos: §5.2 (`verify` → `observe()` no histórico do planner, `focused_value`),
> §5.3 (`done` exige ação executada — guard 4), §10 (tray + Spotlight + ditado, `e35187f`).
> Pendentes: §5.4 (`json_schema`), §5.5 (contexto `tipo:nome`), §6.2 (run dir/dry-run),
> §6.3 (README com comandos dos `llama-server`, LICENSE — escolha do autor), §7 (harness),
> §4.2/4.4/4.5 (invoker `-Reuse`/`-Prune`, cache por boot).

| Prioridade | Item | Esforço | Seção |
|---|---|---|---|
| P0 | Reencodar 4 arquivos (mojibake/BOM) + teste anti-regressão + `.editorconfig`/`.gitattributes` | 1 h | C1, §6.1 |
| P0 | `UV_PROJECT_ENVIRONMENT` no bootstrap (+ `UV_CACHE_DIR`) | 30 min | C2 |
| P0 | Offset do desktop virtual + `SetProcessDpiAwareness` + teste | 1 h | C3 |
| P0 | `type` via `send_keys`/clipboard + teste | 1 h | C4 |
| P0 | Overlay órfão; whitelist `open_app`; `os.startfile` em `open_url` | 1 h | C5, C6 |
| P0 | `presses`/`MIDDLE_CLICK`/`hscroll`/`ANSWER`/multi-ação no Vocaela | 2 h | C7 |
| P1 | `ruff` em dev-deps + limpeza de código morto + `.python-version` + LICENSE + CI | 2 h | §3, §6.1 |
| P1 | Ordem bootstrap→planner; retries fora de `max_steps`; `forced_vision` → `last_error`; `n`→`retries`; `stop_hotkey` ligado; ESC removido | 2 h | C8–C14 |
| P1 | `verify` com observação estruturada devolvida ao planner; `done` condicionado | 4 h | §5.2, §5.3 |
| P1 | README: comandos dos dois `llama-server`; sincronizar ESC; `.SYNOPSIS` dos `.ps1` | 1 h | §6.3, §4.1 |
| P2 | `response_format: json_schema` no planner | 2 h | §5.4 |
| P2 | `tipo:nome` + priorização de controles interativos; walker mais rápido | 4 h | §5.5 |
| P2 | Harness `evals/` + bateria oficial no Sandbox | 1 dia | §7 |
| P2 | Diretório por run com prompts/respostas; `--dry-run`; `--replay` | 4 h | §6.2 |
| P2 | `-Reuse`/`-Force`/`-Prune` no invoker; cache de Python/uv por boot | 3 h | §4.2, §4.4, §4.5 |
| P3 | `Config` pydantic; `httpx.Client` reutilizado + retry/backoff; timeouts menores | 3 h | §3, §5.6 |
| **P1 (novo)** | Tray (`pystray`) + janela Spotlight (`pywebview`) + hotkey global; extra `ui` | 4 h | §10 |
| **P1 (novo)** | Ditado ao vivo `stt.py` (faster-whisper int8, parciais, silêncio → envio) | 4 h | §10 |

## 10. Adição ao plano — ícone na tray + janela Spotlight + ditado ao vivo

> Pedido em 18/09: "ícone na tray e uma interface minimalista como o Spotlight
> com caixa de texto + botão enviar + botão de voz". Esclarecido: o botão de voz
> é **STT (ditado)** — o texto aparece **enquanto** o usuário fala; durante a
> gravação há dois botões (**Parar** → o texto fica na caixa, editável;
> **Enviar**); silêncio por alguns segundos envia sozinho.

### 10.1 Decisões

| Tema | Decisão | Motivo |
|---|---|---|
| UI | **pywebview** (WebView2 do Win11) para a janela + **pystray** para a tray | Visual Spotlight em HTML/CSS sem gambiarra de `ctypes`; ~30–50 MB; `pystray` só precisa de Pillow (já dep). PySide6 (+100–150 MB) foge do "ultraleve"; tkinter puro exige `DwmSetWindowAttribute` p/ cantos/sombra. Fontes: <https://pywebview.flowrl.com/examples/pystray_icon>, <https://github.com/moses-palmer/pystray> |
| Threading | `webview.start()` bloqueia a thread principal; `pystray.Icon.run()` em thread daemon; agente (`loop.run`) em thread própria; `window.evaluate_js` é thread-safe p/ empurrar log/parciais | Padrão do exemplo oficial pywebview+pystray |
| Hotkey global | `ctrl+alt+space` (config `ui.hotkey`) via `keyboard` (já dep) mostra/esconde a janela | Não colide com `alt+space` (menu da janela) nem com `ctrl+alt+esc` do stop |
| STT | **faster-whisper** (CTranslate2, `int8`, modelo `base` por padrão, `small` opcional) via adapter `stt.py` | Melhor relação qualidade pt-BR × tamanho (`base` ~74 MB, ~0,3–0,6 s por frase em CPU) sem torch; VAD Silero embutido (`vad_filter`). Vosk pt-BR (~45 MB) tem parciais nativas mas qualidade inferior; sherpa-onnx SenseVoice (~100 MB) é ótimo mas offline (sem parciais). Fontes: <https://github.com/SYSTRAN/faster-whisper>, <https://github.com/alphacep/vosk-api>, <https://github.com/k2-fsa/sherpa-onnx> |
| "Ao vivo" | Whisper não é streaming: a cada ~1 s retranscreve o buffer da fala atual (≤ 30 s) e mostra como **parcial**; ao detectar silêncio (RMS abaixo do limiar por `stt.silence_ms`, padrão 1500) faz a transcrição **final** e, se `stt.auto_send`, envia | Técnica usada pelos apps de ditado local; custo aceitável com `base int8` |
| Dependências | extra opcional `ui` no `pyproject` (`uv sync --extra ui`) | O Sandbox e a CLI continuam leves; `bootstrap.ps1` não instala a UI |
| Microfone | `sounddevice` (PortAudio embutido na wheel), 16 kHz mono float32 | Zero setup no Windows |
| Isolamento | A janela **se esconde** antes de o agente agir (`loop.run`) e reaparece no fim; nunca aparece nos screenshots do Vocaela nem rouba foco | Mesma regra do overlay |

### 10.2 Alternativas registradas (não escolhidas)

- TTS (leitura do resultado) não foi pedido; se um dia for: Piper `pt_BR-faber` (~20–60 MB, RTF < 0,05, fork ativo `OHF-Voice/piper1-gpl` é GPL-3) ou Kokoro-82M ONNX (vozes `pf_dora`/`pm_alex`, Apache 2.0, ~330 MB). Fontes: <https://github.com/OHF-Voice/piper1-gpl>, <https://huggingface.co/hexgrad/Kokoro-82M>, <https://pypi.org/project/kokoro-onnx/>.
- STT com parciais nativas: Vosk `vosk-model-small-pt` (~45 MB) — trocar só `stt.py` (`Engine` plugável).

### 10.3 Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | tray + janela + hotkey + `JsApi` (enviar, ditado start/stop, status) + agente em thread |
| `ui/index.html` | Spotlight: input, mic, Enviar/Parar, linha de status, log dos steps |
| `stt.py` | `Dictation` (mic → parciais → silêncio → final) com `Engine` plugável; `FasterWhisperEngine` |
| `config.py` | seções `ui` (`hotkey`, `width`, `auto_hide`) e `stt` (`model`, `compute_type`, `language`, `silence_ms`, `partial_every_ms`, `auto_send`) |
| `main.py --ui` | sobe o app em vez da CLI |

### 10.4 Testes (offline, sem mic/modelo)

`Dictation` recebe `Engine` e `source` de áudio falsos: parciais emitidas no intervalo certo; silêncio dispara `on_final` uma vez; `stop()` sem enviar mantém o texto; `auto_send=False` nunca envia. `JsApi` testado sem webview (callbacks capturados). `index.html` existe e referencia a API (`pywebview.api.*`).

## Apêndice — como reproduzir os achados

```bash
# C1: mojibake e BOM
grep -n 'Ã\|â€' planner.py main.py config.py tests/test_two_models.py
head -c 3 planner.py | od -c        # 357 273 277 = BOM

# §4.3 / §6.1: Python e ruff
uv run python -c "import sys; print(sys.version)"   # 3.14.6 (sem .python-version)
uv run ruff check .                                 # "program not found"

# C15: sockets nos testes
uv run python -X dev -m unittest discover -s tests 2>&1 | grep ResourceWarning

# §3: símbolos mortos
grep -n '_extract_text_to_type\|_extract_digit\|_extract_search_query\|foreground_title' loop.py
grep -rn 'click_element\|list_windows\|TOOLS\b' --include=*.py . | grep -v '.venv\|def '
```
