# Relatório parcial R0–R3 — integração e primeiro probe de capacidade

Data: 20/09/2026. Este relatório não aprova execução end-to-end nem muda o
default. Testes com inputs físicos continuam pendentes no Windows Sandbox.

## Implementado

- Estado compacto da tarefa e resultado da última ação chegam ao planner
  textual e ao unificado.
- `done` exige referência exata a evidência observada. Histórico de ações e
  mudança de título deixaram de ser evidência implícita.
- Resultado sem efeito confirmado não entra na memória como evidência.
- Conclusão é registrada na trajetória; o runner live lê a trajetória completa.
- Checkers não aprovam mais tarefa apenas por ausência de crash/loop. `false_done`
  significa conclusão declarada com resultado reprovado pelo checker.
- Anti-loop compara fingerprint de título + elementos UIA observados.
- Fixture sanitizada `evals/fixtures/nova-guia-stuck.json` e probe sem inputs.
- CLI do runtime unificado corrigida para subir um processo/endpoint.

Validação offline: 215 testes e `ruff check` verdes. `main.py --self-test`
passou. Dry-run registra N/A/reprovação nos checkers sem oráculo, sem convertê-los
em sucesso funcional.

## Probe real, sem mouse/teclado

Cena: Chrome já aberto, aba nova já criada, essas duas etapas registradas como
concluídas; próximo passo deve avançar para navegação/pesquisa. Uma decisão é
válida se não reabrir/focar o browser nem repetir `ctrl+t`.

| Perfil | Resultado | Decisões | Latência observada |
|---|---:|---|---:|
| B1 / MiniCPM5-2B textual | 0/3 | `hotkey(ctrl+t)` ×3 | 3,22 s primeira; 0,75/0,71 s aquecidas |
| U1 / Qwen3-VL-2B unificado | 3/3 | `hotkey(ctrl+l)` ×3 | 53,85 s primeira; 37,99/37,62 s aquecidas |

Uma execução B1 anterior, com a fixture excessivamente anonimizada como
“Navegador”, escolheu `open_app(chrome)` em 22,03 s. Ela foi descartada da taxa:
o título anonimizado removeu a evidência de que o Chrome estava ativo. Depois de
corrigir a fixture para `Google Chrome`, o B1 ainda falhou 3/3.

O primeiro lote U1 foi iniciado indevidamente em três chamadas concorrentes e
excedeu o KV cache; foi cancelado, o servidor reiniciado e as três medições acima
foram feitas sequencialmente. Esse lote cancelado não entra na qualidade.

## Decisão parcial

B1 está inelegível para investimento adicional como planner principal até que
uma mudança de modelo/adapter/contexto, genérica e previamente delimitada,
melhore os probes. Não adicionar guards por site/tarefa para fazê-lo passar.

U1 demonstrou a decisão correta nesta única cena, mas falha o alvo de latência
no runtime atual. O log confirma `ngl=0` em binário CPU-only; este resultado não
avalia o gate de GPU de 6 GB. U1 segue candidato a medir com backend GPU real.

R3 ainda não está concluída: faltam pelo menos 30 cenas ×3, leitura visual,
alvos ausentes/duplicados, contrafactuais e medição em GPU. R4/R5 também seguem
pendentes; nada aqui autoriza declarar o app funcional.
