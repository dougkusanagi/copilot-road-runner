# Histórico de avaliação — probes e perfis anteriores a R0–R6

> **Histórico, não normativo.** Seguir exclusivamente o
> [plano vigente R0–R6](plano-agente-generico-2026-09-20.md).
> Gates, ordem de modelos, alegações de F0–F6 concluídas e instruções de
> default/rollback abaixo foram substituídos. Há contradições preservadas
> neste relato (B0/B1); o default atual é B1 e o rollback é `--profile B0`.
> Checkers e conclusão exigem auditoria R0/R1 antes de embasar promoção.

Registro original: 20/09/2026. Referências numéricas de seções/F7 abaixo
pertencem ao plano antigo removido; não são instruções de implementação.

> Replay de observações é diagnóstico offline, não prova end-to-end.
> Bateria completa (100 runs) exige GPU física de 6 GB + Sandbox; abaixo,
> o piloto executável neste ambiente + critérios para promover um perfil.

## 1. Piloto executado aqui (sem GPU/Sandbox)

```powershell
uv run python -m unittest discover -s tests   # 171 verdes (F0–F6)
uv run ruff check                             # limpo
uv run python -m evals.runner --pilot --dry-run   # 5 tarefas, dry_run_ok, sem clicar no host
uv run python main.py --self-test             # sem clicar em nada
```

Resultado: piloto dry-run `dry_run_ok` nas 5 tarefas pilot (notepad-acentos,
notepad-ja-cumprido, calc-soma, web-busca, vis-canvas); checkers que exigem
fixture/Sandbox registram `N/A` (não contam como prova end-to-end).
Suite offline cobre contratos, timeout, cancelamento, retries, efeitos
desconhecidos, conclusão inicial, stale frames/refs, Unicode, OOM/orçamento,
skill ausente e sequências — sem espelhar texto de implementação.

## 1b. Probes somente-leitura no planner real (19/09, zero efeitos no desktop)

Instrução real que travou em loop (`focus("Google")` ×6 + `wait(0ms)` ×3).
Com o prompt/guards novos, o mesmo MiniCPM5-1B local decidiu:

1. bootstrap step0 → `open(chrome)` (browser entra no bootstrap, como
   notepad/calc — antes o 1B focava o PowerShell e nunca abria o app);
2. com Chrome ativo → `sequence(ctrl+l, enter)` (age DENTRO, sem copiar o
   exemplo, sem focus);
3. pós anti-repetição → passo misto `press_key+keys` (malformado; agora
   rejeitado com dica `use hotkey`, em vez de executar `hotkey(enter)`
   errado).

Progresso real, mas honestidade: o 1B ainda não incluiu o `type_text`
(amazon/rtx) sozinho nos probes — tarefa web multi-step segue incerta no
B0. É exatamente o que B1/D/U devem comparar na bateria (§3, ordem
B0 → B1 → U1/D1/D2).

## 1c. Iteração no run real 22:58 (picker de perfil + sequence fantasma)

- Causa do stall: ramo `sequence` inalcançável executava `wait(0)` sem
  validar (open_app com `url` inventado dentro de sequence passava batido).
  Fix + teste de regressão; `sequence` agora veta tipo proibido e passo
  misto `press_key`+`keys`.
- Janela nova do Chrome caiu no seletor de perfil ("Quem está usando?",
  Seu Chrome vs Silver): bootstrap virou focus-first (janela existente =
  perfil certo, sem picker). Escolher perfil = escolher dados de alguém →
  nova ação `ask` (human-in-the-loop, teto 3/run, timeout 60 s, sem travar
  sem humano) + `prefs.json` (pergunta 1 vez, lembra `browser_profile`,
  preferência entra no prompt e é aplicada sozinha).

## 1d. Probe 23:12 (receita ctrl+t no prompt, zero efeitos)

Mesmo 1B, mesma cena (aba Atelier ativa, "abra nova aba + amazon"): decidiu
`sequence(hotkey ctrl+t, press enter)` — a combinação inventada
(`ctrl+alt+n`, 5x sem efeito no run real) sumiu com a receita no contexto.
Ainda sem o `type_text` sozinho; o loop agora observa as combinações
(`_verify_action`), avisa "no visible effect" + receita, e o anti-loop cita
o conteúdo da sequence em vez de `wait` genérico.

## 1e. Probe B1 20/09 (download + primeira decisão, zero efeitos)

- Download oficial `MiniCPM5-2B-Q4_K_M.gguf` (1.561 MB) pelo runtime,
  carga e serve OK nas mesmas flags (`--jinja`).
- Mesma cena: B1 decidiu `hotkey ctrl+t` (nova aba, correto) em **18,7 s**
  na primeira inferência no CPU (6 threads) — qualidade certa de primeira,
  custo ~2–3× a latência do 1B aquecido. Medir aquecido + comparar B0×B1
  em `runs/` no uso real antes de qualquer conclusão de latência.

## 2. Matriz de perfis (candidatos, §3)

| ID | Planner | Visão | Modo | Status nesta máquina |
|---|---|---|---|---|
| B0 | MiniCPM5-1B | Vocaela-2-500M-1024R2 | duplo | Rollback (`--profile B0`); baseline da comparação |
| B1 | MiniCPM5-2B | Mesmo Vocaela | duplo | **DEFAULT desde 20/09 (pedido do usuário)**. GGUF oficial [openbmb/MiniCPM5-2B-GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF) (`MiniCPM5-2B-Q4_K_M.gguf`, ~1,5 GB, mesmas flags `--jinja`); isola o efeito 1B→2B. Comparação B0×B1 em `runs/` pendente |
| D1 | MiniCPM5-2B | Qwen3-VL-2B-Instruct | duplo | Idem: sem GGUF/manifesto → inelegível |
| D2 | MiniCPM5-2B | Qwen3.5-2B | duplo | Idem |
| U1 | Qwen3-VL-2B-Instruct | mesmo | unificado | Executável com `--profile U1`: GGUF Q4_K_M + mmproj F16; uma captura por decisão; falta benchmark real |
| U2 | Qwen3.5-4B único | mesmo | unificado | Hipótese p/ 6 GB; idem |
| G1 | MiniCPM5-2B | GUI-Owl-1.5-2B-Instruct | duplo | Opcional; só após vencedor D1/D2 |
| E1 | Empero Qwen3.8-2B-Distill | Vocaela | duplo | Opcional; só texto até prova de visão (§3.1) |
| E2 | Empero único | a validar | unificado | Indisponível sem artefato multimodal completo |

Ordem: B0 → B1 → U1/D1/D2 → U2 → G1/E1/E2. Não executar todos de uma vez
nem somar terceiro modelo ao caminho obrigatório.

## 3. Gates (§9.3) — posição atual

1. **Safety:** zero violações janela/frame observadas na suite; `release_all`
   em exceção/cancelamento; executor único; `test_refactor` trava.
   Falsos done: `done_evidence_ok` veta sem evidência/obsoleta (suite).
2. **Sucesso ≥90% nas 20 tarefas:** pendente de bateria Sandbox em GPU
   física (piloto dry-run ≠ prova). Não declarar antes dos 100 runs.
3. **VRAM:** `telemetry.collect_env` + `model_adapters.vram_budget_ok` medem
   dedicada/compartilhada; `server.gpu_status` avisa ngl em binário CPU.
   Sem OOM/spill medido aqui (sem GPU) → gate aberto.
4. **Promoção de default:** sem evidência de ≥20% mediana mais rápida ou
   ≥10 p.p. sucesso (p95 +≤25%) → **default permanece B0**. Comparar com B0
   original e B0 no novo loop quando houver números.
5. **Latência aquecida (p95 decisão textual ≤1,5 s, visual ≤3 s):** medir do
   estado pronto à decisão validada na bateria; registrar gargalo se falhar.

## 4. Ablações previstas (um fator por vez, nos finalistas)

1B/2B, Vocaela/VLM, duplo/unificado, memória on/off, sequência/ação única,
observação reaproveitada/nova, Q4/Q5, contexto 4K/8K, resolução e modo de
raciocínio. `http_pool.stats()` + `runs/<id>/` dão chamadas por modelo,
UIA/captura/prefill-geração/execução/verificação, TTFT e p50/p95.

## 5. Rollback

- Default B0: `config.json` sem `profile` (ou `"profile": "B0"`).
- Rollback B1: `"profile": "B1"` usa mesmo Vocaela; planner volta a 1B
  removendo a chave. Config legado continua migrável; `profile_of({}) = B0`
  travado em `test_refactor`.
- Nenhum dado de usuário em `runs/` é versionado (gitignored); manifestos
  de pesos em `models/manifest.json` fixam revisão por perfil.

## 6. Decisão

**B1 como default desde 20/09, por pedido do usuário** (desvio consciente do
gate §9.3.4: a bateria B0×B1 ainda está pendente e fica registrada em
`runs/` — rollback é `--profile B0`). Hipótese: o 2B monta sequências
completas (`ctrl+t`, `ctrl+l` + `type` + `enter`) onde o 1B inventava
combinações e stallava; custo esperado é ~2× latência por decisão no CPU.
F0–F6 implementados e testados offline; a comparação B0×B1 em tarefa real
é o próximo dado a coletar.
