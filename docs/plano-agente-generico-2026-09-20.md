# Plano vigente — agente genérico local com resultado verificável

Data: 20/09/2026. **Status: proposto; nenhuma etapa abaixo está aprovada por
existir código ou por passar testes com mocks.** Este é o único backlog de
refatoração vigente. Substitui integralmente o plano de 19/09 (removido).
A revisão de 18/09 e a matriz anterior são registros históricos, não instruções
de execução. As antigas fases F0–F7 não correspondem às etapas deste plano.

## 1. Resultado esperado e limites do compromisso

Receber um pedido novo em português, observar o computador, escolher ações,
executá-las com mouse/teclado reais, verificar o resultado e responder com
evidências. Exemplos de classes: pesquisar informação na web, editar e salvar
um documento, manipular arquivos pela interface, ajustar uma preferência e
transferir informação entre aplicativos. Não criar receitas por loja/produto,
gabaritos de sequência ou roteamento por palavras do pedido para fazê-los passar.

Requisitos mantidos:

- Operação normal local, sem API comercial obrigatória. GPU de 6 GB é o alvo
  mínimo a demonstrar, não uma capacidade presumida. Não há requisito de usar
  exatamente 1B/2B nem de manter dois modelos.
- Python observa, valida, executa e registra. O modelo escolhe estratégia,
  aplicação, alvo, subobjetivo, recuperação e momento de pedir ajuda.
- UIA pode ler e localizar; ações GUI usam inputs físicos. Sem navegação por
  `open_url`, escrita semântica invisível, DOM/CDP/Playwright como atalho oculto,
  ou shell arbitrário. Skills CLI explícitas continuam em modo separado.
- Preservar FAILSAFE, ctrl+alt+esc, Unicode, dry-run sem efeitos, cancelamento,
  liberação de teclas/botões, executor único, UI opcional e STT inicialmente CPU.
- Testes dev com inputs exclusivamente no Windows Sandbox, pelos scripts
  existentes. Limitação de Sandbox exige ambiente dedicado; nunca testar clicando
  no desktop de trabalho. Uso normal pelo usuário continua local no host.
- Ambiguidade real pode gerar `ask`; captcha/credenciais/permissões podem gerar
  bloqueio ou ajuda humana. Não contornar captcha nem contar ajuda como autonomia.

O compromisso é testar a viabilidade e implementar uma base correta. Se nenhum
modelo elegível atingir os gates, entregar diagnóstico de inviabilidade no
hardware/escopo medidos. Não declarar o produto funcional nem preencher a
capacidade ausente com regras por tarefa.

## 2. Diagnóstico de partida: código existente não é validação funcional

Referência local: `runs/run-20260920-005256/` (gitignored; preservar ou exportar
amostra sanitizada para fixture). Pedido: nova aba e preço de RTX 5090 na Amazon.
Resultado: stuck, 66,2 s, 9 chamadas de planner, 0 de visão; repetição de ctrl+t.
Isso demonstra falha de planejamento/progresso nesse run, não falha de grounding
nem prova geral de impossibilidade com modelos pequenos.

Achados a reproduzir com testes de integração:

| Área | Situação encontrada | Consequência / trabalho necessário |
|---|---|---|
| Memória | `TaskState` existe; `_ask_planner` não envia seu resumo; `task_update` veio nulo no run | Conectar observação, resultado e estado ao contexto real, não só criar dataclasses |
| Conclusão | `done_evidence_ok` admite histórico de ação como evidência implícita; também compara substrings | Remover esse caminho no novo motor; ação enviada não prova objetivo cumprido |
| Verificação | `verify`/`observe` usam fortemente título; `confirm_effect` deixa efeitos pendentes | Verificar mudança relevante, incluindo foco/campo/aba/modal/conteúdo |
| Anti-loop | `_progress_made` compara textos das notas | Comparar ação, estado relevante e efeito; textos diferentes não são progresso |
| Percepção | UIA do Chrome trouxe 6–7 itens de moldura; nenhuma visão foi solicitada | Informar cobertura e oferecer leitura visual de conteúdo, não somente coordenadas |
| Contratos | Schema amplo com campos nulos, compatibilidades e sequence representada como wait | Tipos discriminados realmente usados de ponta a ponta; sem ações fictícias |
| Avaliação | Runner dry-run não executa o loop; live passa resumo aos checkers, não trajetória completa; alguns checkers aprovam ausência de loop | Construir fixtures e oráculos independentes de resultado; N/A não é aprovação |
| Métricas | VRAM global de nvidia-smi/estimativas por perfil não provam offload nem pico do agente | Medir processo/backend/picos/carga de desktop; sem atribuir VRAM total ao modelo |

Preservar os testes úteis, mas revisar os que cristalizam essas compatibilidades.
Não usar o número de testes, JSON válido ou uma primeira ação correta como prova
de capacidade. Relatos antigos de “F0–F6 implementadas” são inventário histórico.

## 3. Reaproveitamento e escolha de base

Decisão inicial: manter o projeto Python e seu executor enquanto se mede uma
alternativa. Não fazer uma reescrita integral antes de isolar modelo e motor.
Não instalar três frameworks no caminho de produção.

| Base | Uso proposto | Gate para adoção |
|---|---|---|
| [UI-TARS Desktop](https://github.com/bytedance/UI-TARS-desktop) | Primeira referência externa para ciclo visual, operadores, trajetória e UX | Spike no Sandbox com endpoint local compatível; registrar adaptação, licença, commit e custo. Adotar componentes ou base somente com ganho demonstrado |
| [Agent S](https://github.com/simular-ai/Agent-S) | Referência Python para trajetória visual e recuperação | Sua configuração recomendada combina modelo principal forte e grounding UI-TARS-1.5-7B; resultados publicados não validam 2B/6 GB. Não copiar execução irrestrita de código |
| [UFO²](https://github.com/microsoft/UFO/tree/main/ufo) | Consultar integração Windows e observação UIA | Separar GUI de APIs; reaproveitar apenas componentes que respeitem nosso contrato |
| [Pi Agent Core](https://github.com/badlogic/pi-mono/tree/main/packages/agent) | Opção futura para infraestrutura geral em TypeScript | Não é dependência desta refatoração. Adotar só se eventos, ferramentas e contexto justificarem Node + ponte Python em comparação com o loop mínimo |

O Pi mantém mensagens, ferramentas, eventos, cancelamento e transformação de
contexto; não entrega percepção de desktop, verificação de objetivos ou capacidade
extra ao modelo. [Pi AI](https://github.com/badlogic/pi-mono/tree/main/packages/ai)
suporta endpoints compatíveis, mas tool calling deve ser testado. Se adotado,
ações físicas são sequenciais e passam pelo executor existente. Fixar versão e
API: nomes de pacotes e comportamento podem mudar.

As referências foram consultadas em 20/09/2026. Antes de copiar ou integrar,
conferir README, licença, dependências, commit e compatibilidade atuais. Não
confundir app local com inferência local. Nenhum desses repositórios, nas fontes
consultadas, comprova nosso objetivo específico em 6 GB.

## 4. Arquitetura de destino: um ciclo pequeno, rastreável e completo

`pedido → observação → decisão + atualização proposta → validação → execução
→ observação do efeito → resultado + memória → próxima decisão`

Cada componente precisa ter um uso real no loop e um teste que atravesse suas
fronteiras. Reutilizar `schemas.py`, `state.py`, `obs.py`, `uia.py`,
`verification.py`, `model_adapters.py`, `telemetry.py`, `actions.py` e `safety.py`;
extrair gradualmente de `loop.py` contexto, validação, execução e recuperação.
Nomes de novos módulos são escolhas de implementação, não motivo para duplicar
o código. Manter CLI, configuração e UI como clientes do mesmo motor.

### 4.1 Contratos e memória realmente consumidos

- `Observation`: ID, instante, HWND/PID/app, janelas/monitores, foco, modal,
  elementos com IDs locais, nome/papel/valor/estado/ancestral/bounds, cobertura,
  truncamento, erros e referência do frame. Título não é identidade da janela.
- `Decision`: união discriminada entre ação, percepção, pergunta, skill e
  conclusão. Argumentos estritos por tipo, referência da observação, efeito
  esperado e atualização compacta de estado. Nada de dezenas de nulos ou
  `wait(0)` para representar algo que não é espera.
- `ActionResult`: ID, enviado/não enviado/incerto, efeito confirmado/não
  confirmado/contradito, erro estruturado, observação posterior e evidências.
  Uma falha após envio não permite retry automático do input.
- `TaskState`: requisitos escolhidos pelo modelo a partir do pedido original,
  subobjetivo atual, pendências, concluídos com evidências, fatos, hipóteses,
  falhas ainda relevantes, skill ativa e limites restantes. Registrar a
  atualização proposta separadamente da aceita.
- `Evidence`: ID, origem (UIA/OCR/visão), observação/frame, conteúdo e escopo
  temporal. O modelo só referencia IDs fornecidos. Python valida existência,
  proveniência e vínculos; interpretação semântica permanece falível e é
  auditada. Não transformar alegação do próprio modelo em fato confirmado.

O prompt de cada decisão recebe pedido original, estado compacto, observação
atual, última ação/resultado, falhas relevantes e ferramentas disponíveis.
Limitar por orçamento de tokens, preservando objetivo, pendências e erros
não resolvidos; não simplesmente cortar as últimas cinco strings. Observações
e conteúdo de sites são dados não confiáveis, nunca novas instruções de sistema.

Atualizações de concluídos precisam apontar evidências posteriores à ação
quando aplicável. Evidência histórica de um arquivo salvo pode continuar válida;
referência usada para clicar exige observação atual. Não invalidar todo fato
histórico só porque a tela mudou. Preferências persistidas são dados do usuário,
separados dos fatos da execução.

### 4.2 Observação e leitura de conteúdo

- Corrigir e instrumentar UIA antes de aumentar indiscriminadamente seu tamanho:
  distinguir provider sem conteúdo, filtro incorreto, timeout e truncamento;
  oferecer expansão de ramo solicitada pelo modelo e preservar textos úteis.
- Dar IDs aos elementos e contexto a nomes repetidos. Localização UIA pode
  resultar em centro do elemento para clique real, depois de validar bounds,
  visibilidade, foco e oclusão. Não resolver alvo ambíguo por primeiro match.
- Introduzir percepção visual com retorno de fatos/texto e evidências, além de
  grounding. Vocaela continua candidato a localizador; não presumir que lê
  ofertas, preços ou diálogos adequadamente. OCR local é complemento mensurável.
- No perfil unificado, o modelo vê um frame atual por decisão; se já pode
  fornecer ação vinculada ao frame, evitar segunda chamada de grounding sem
  necessidade. No duplo, o planner textual não recebe pixels/coordenadas, mas
  recebe os fatos retornados pela percepção e pode pedir recorte/expansão.
- Capturar janela/monitor solicitados com origem, escala, DPI e tamanho.
  Converter coordenadas uma vez; cobrir monitor com origem negativa. Recortes
  carregam transformação explícita. Mudança externa/modal invalida alvos.
- Reaproveitar observação posterior somente enquanto válida. Provider COM
  travado precisa de timeout efetivo e isolamento/cancelamento de worker.

### 4.3 Execução, confirmação e recuperação genéricas

- Remover gradualmente bootstrap/roteamento por palavras do pedido. Descobrir
  janelas e apps instalados, expor catálogo ao modelo, e abrir o ID escolhido
  por mecanismo validado sem shell. Manter whitelist enquanto o catálogo seguro
  não existir; não ampliar comandos por concatenação livre.
- Permitir primitivas genéricas: abrir/focar, clicar, digitar, teclas, scroll,
  arrastar e esperar condição. Skills ensinam capacidades de ferramentas, não
  trajetórias para os testes. Nenhum `if amazon`, produto ou título de fixture.
- Sequências de até três primitivas só com dependências e precondições
  explícitas. Conferir identidade de janela/foco entre passos; observação nova
  quando a ação puder mudar alvo/modal. Nunca representar sequência como wait.
- Substituir a regra “URL só após ctrl+l” por precondição demonstrável de alvo
  apropriado. Ctrl+l é um modo de obter foco; barra já focada também pode ser
  válida. Sem evidência de foco, retornar motivo ao modelo, não digitar no escuro.
- Confirmar conforme o efeito: campo/valor, aba criada/selecionada, modal fechado,
  seleção alterada, conteúdo visível. Ctrl+t não é tecla de foco; ausência de
  mudança de título não prova sucesso nem fracasso de nova aba.
- Esperas canceláveis com prazo e condição; sem sleeps fixos como verificação.
  O modelo interpreta efeitos quando só a imagem informa; código verifica
  invariantes e predicados observáveis delimitados, não executa código do modelo.
- Anti-loop considera ação + alvo + estado relevante + resultado. Repetição
  com progresso (scroll com novo conteúdo) é distinta de repetição sem efeito.
  Rejeições são parte do histórico, sem apagar custo/decisão. Não proibir
  genericamente todo `focus` por o navegador estar ativo.
- Após falta de efeito: reobservar, devolver resultado e deixar o modelo
  escolher alternativa/percepção/ajuda. Teto separado para ações, decisões,
  chamadas de percepção, retries e tempo. Retentativa HTTP não reenvia inputs.
- Cancelamento interrompe filas e libera teclas/botões mesmo em exceção. Inputs
  adicionais após stop são falha de segurança. Preservar controle exclusivo.

### 4.4 Conclusão e resposta ao usuário

`done` exige cobertura dos requisitos e evidências, inclusive se o objetivo já
estiver satisfeito na observação inicial. Uma ação executada, mudança de título
ou resposta textual do modelo não bastam. Remover evidência implícita e matching
por substring do novo motor; não mantê-los como fallback silencioso.

Para consulta de informação, a saída deve trazer a informação solicitada, não
só “done”. Na pesquisa de preço: produto/variante, valor, moeda, fonte observada
e ressalva se a oferta não estiver acessível. Não inventar preço nem inferir de
conhecimento prévio. Esse é um critério de avaliação de resultado, não receita
de navegação. Status distintos: sucesso, parcial, bloqueado, cancelado, orçamento
esgotado e erro técnico. Ajuda humana e faltas de evidência aparecem no resumo.

## 5. Modelos e runtime: seleção por capacidade, não por nome

B1 permanece default durante a avaliação; B0 é rollback. O U1 implementado
atualmente usa **Qwen3-VL-2B-Instruct**, não o checkpoint que o plano antigo
atribuía ao mesmo ID. Registrar identidade completa; não reinterpretar aliases
existentes silenciosamente. Novos candidatos recebem IDs inequívocos.

Comparar primeiro B1 corrigido e U1, depois no máximo dois candidatos elegíveis
de 2B–4B ou especialistas GUI. Um 7B só entra no alvo de 6 GB se couber e passar
latência/reserva medidos; tamanho do GGUF não é pico de VRAM. Não baixar toda a
matriz antiga. Modelos comunitários, incluindo `empero-ai/Qwen3.8-2B-Distill`,
exigem confirmar arquitetura, pesos, projetor e template; nome não prova visão.

Antes da bateria:

1. Fixar repositório/revisão/hash/licença dos pesos, projetor, runtime, template,
   quantização, contexto, resolução, orçamento de saída e parâmetros de geração.
2. Verificar JSON/contrato (ou tool calling, se adotado), português, leitura
   visual, alvo ausente, alvo duplicado e duas imagens diferentes com mesmo
   pedido. Medir planejamento separadamente de localização e leitura.
3. Confirmar backend e offload real pelos logs/processos, além de nvidia-smi.
   Medir cold start, primeira inferência e aquecido; separar UIA, captura,
   prefill/geração quando disponíveis, validação, execução e verificação.
4. Medir pico de memória dedicada e compartilhada, RAM, desktop em repouso e
   sob carga, resolução e GPU. Uma geração ativa por GPU; STT CPU. Alvo: agente
   até ~5 GB de dedicada em placa de 6 GB, com ~1 GB reservado ao desktop;
   registrar consumo total também. Sem OOM nem spill sustentado escondido.
5. CPU-only ou offload parcial podem servir ao diagnóstico, mas não aprovam o
   gate de GPU. Endpoint vivo deve corresponder ao modelo/capacidades esperados;
   erro de construção do adaptador não pode escolher outro perfil silenciosamente.

Evitar prompts extensos e chamadas de planejamento/reflexão para toda primitiva.
Começar com uma decisão por observação e recuperação apenas quando necessária.
Compactar contratos/contexto e medir ablações. Otimização só vale se preserva
sucesso; quantização menor e mais tokens/s não significam agente melhor.

## 6. Avaliação que separa integração, capacidade e produto

### 6.1 Três níveis, resultados nunca intercambiáveis

**Contratos offline:** mocks exercitam invariantes e fronteiras, não inteligência.
Cobrir stale frame/element, foco trocado, envio incerto sem duplicar texto,
sequência interrompida, cancelamento, Unicode, dry-run completo, done falso e
propagação de estado/percepção ao prompt real. Não aprovar pelo texto de um prompt.

**Probes com modelos reais sem inputs:** fixture sanitizada de observação +
estado + resultado anterior, incluindo o caso Nova guia. Avaliar classes de
decisões válidas por estado, não exigir uma sequência única. Pelo menos 30 cenas,
3 repetições, variações de idioma/layout/estado e imagem contrafactual.
Gate para investir em E2E: ≥90% decisões semanticamente válidas, ≥99% formato
válido e zero tentativas executáveis que violem invariantes. Separar erro de
formato, planejamento, percepção e grounding. Esses números são metas propostas,
não resultados nem demonstração de autonomia.

**E2E Sandbox:** fixture prepara estado, agente recebe só pedido/observação e
checker independente inspeciona resultado. Instrumentação de teste pode ler
arquivo/estado interno para conferir, sem oferecer esse atalho ao agente GUI.
Passar a trajetória completa aos checkers. `false_done` significa declaração
de sucesso com resultado incorreto, não qualquer stuck. `no_crash` e ausência
de loop são métricas auxiliares, nunca sucesso de tarefa. N/A/skip ficam fora
do numerador e explícitos no denominador, sem aprovação automática.

### 6.2 Bateria e independência

Manter 20 tarefas de desenvolvimento e reservar 20 tarefas de aceitação, cinco
execuções limpas de cada tarefa de aceitação (100 runs por finalista). Pelo
menos cinco famílias: web/leitura, edição/salvamento, arquivos, configurações,
e transferência entre apps. Incluir objetivos já cumpridos, modal, alvo ausente,
UIA incompleta, nomes duplicados, foco desviado, aba já aberta e resolução
diferente. Começar com ações descartáveis; operações sensíveis exigem casos
isolados e controles próprios, não ampliação implícita da autorização.

Congelar critérios, variantes e orçamento antes de comparar. Não incluir nomes
ou respostas de fixtures no prompt/skills. Holdout deve ser executado após
congelar código; se seus erros motivarem ajustes, ele vira desenvolvimento e
precisa de substituição para nova aceitação. Preferir autor/revisor distinto
para os casos de aceitação quando disponível, sem exigir agentes paralelos.

Páginas locais controladas permitem regressão estável, mas não bastam: incluir
ao menos cinco tarefas de aceitação em sites reais, domínios/layouts variados,
com avaliação manual das evidências dinâmicas. Captcha/indisponibilidade são
bloqueios reportados e contam como não concluídos no sucesso bruto; reportar
também resultado em ambientes acessíveis. Não trocar casos depois de ver falhas.

### 6.3 Gates de promoção do produto

- **Qualidade:** ≥90/100 sucessos autônomos corretos; ≥80% por família; zero
  falsos sucessos observados e zero violações de segurança na bateria. Reportar
  intervalo de confiança e limites da amostra: isso não prova sucesso universal.
- **Ajuda:** registrar número e motivo de intervenções; tarefa concluída com
  ajuda não entra como sucesso autônomo. Bloqueio honesto é melhor que falso
  done, mas não cumpre o gate de funcionalidade.
- **Tempo:** em tarefas curtas, alvo p50 ≤60 s e p95 ≤120 s aquecido; decisão
  aquecida p95 ≤5 s textual e ≤8 s visual, medidos fim a fim até decisão válida.
  Cold start/download separados. Medir chamadas/tarefa, retries e tempo de UIA.
  São limites iniciais de produto; qualquer revisão precisa de justificativa
  registrada antes de nova avaliação, sem chamar desempenho lento de aprovado.
- **Hardware:** passar em GPU física de 6 GB nas condições da seção 5; registrar
  latência/reserva com carga de desktop. Sem acesso ao hardware, gate pendente.
- **Escolha:** comparar mesmos casos e condições; primeiro qualidade e safety,
  depois latência/memória. Não promover por alguns pontos sem examinar variação
  entre runs. Resultado, config e limitações em relatório versionado sanitizado.

Modelo que reprova os probes após uma rodada delimitada de correção de adapter/
template/contexto não recebe novos remendos por app: fica inelegível nessa rodada.
Se nenhum dos candidatos limitados da seção 5 passar, suspender expansão de
features e documentar o gargalo. A decisão de exigir hardware maior/modelo remoto
ou reduzir escopo cabe ao usuário; não alterar os requisitos silenciosamente.

## 7. Ordem de implementação e entregas verificáveis

| Etapa | Entrega e arquivos principais | Critério de saída |
|---|---|---|
| R0 — referência honesta | Inventário do estado Git, baseline dos runs, correção de semântica dos checkers em `evals/`, fixtures/probes e relatório de runtime | Reproduzir offline os defeitos da seção 2; distinguir dry-run, probe e E2E; nenhuma mudança de default |
| R1 — ciclo integrado | Contratos discriminados, memória/contexto em `schemas.py`, `state.py`, `planner.py`, `loop.py`; remoção do done implícito no novo caminho | Teste atravessa observação→decisão→resultado→próximo prompt e impede falso done/duplicação; regressões de segurança verdes |
| R2 — percepção e efeitos | UIA diagnosticável/IDs, leitura visual/OCR opcional, frame/DPI, verificação e anti-loop | Casos reais sanitizados de UIA vazia, preço/texto visual, nova aba e modal; imagem alterada muda evidência; sem confirmação por título apenas |
| R3 — capacidade e base | B1/U1 nos probes; até dois candidatos adicionais; spike UI-TARS e decisão de reutilização | Relatório separa modelo/motor/runtime, inclui memória/latência, e escolhe no máximo dois finalistas; sem candidato aprovado, parar e reportar |
| R4 — fluxo físico | Novo motor no Sandbox, catálogo seguro de apps, sequências/recuperação, remoção gradual de heurísticas por app | Bateria dev com checkers de resultado; cancelamento/foco/stale/Unicode/dry-run aprovados; objetivo original vira informação verificável |
| R5 — aceitação | Bateria congelada 100 runs/finalista, ablações limitadas, relatório e escolha de default | Todos os gates da seção 6 ou relatório explícito de reprovação; não declarar funcional se só offline passou |
| R6 — entrega e limpeza | CLI/UI/runtime/STT, documentação, migração de config, remoção de legado sem uso | Uso normal local simples, erro honesto, rollback documentado, smoke de integração e documentação coerente com medido |

R0→R1→R2→R3 são prioritários. Probes de hardware podem começar em R0; execução
física de experimentos sempre no Sandbox. Não polir UI nem multiplicar skills
antes de passar capacidade. Ao final de R3, registrar uma decisão: continuar
com Python, reaproveitar componentes externos, ou migrar base por ganho medido.
Migração maior só após esse resultado, preservando executor e testes.

Cada etapa gera commit testável com suite verde e relatório curto do que foi
comprovado/pendente. Inspecionar mudanças locais antes de editar/stage; não
misturar trabalho anterior ou segredos/runs no commit. Push conforme workflow.

## 8. Execução pelo próximo agente

1. Ler este plano, `AGENTS.md` e `docs/sandbox-test-env.md`; inspecionar Git e
   implementações atuais. Não executar o roadmap da revisão histórica.
2. Começar R0 com o run que repetiu ctrl+t e os checkers independentes; criar
   fixture sanitizada pequena, sem páginas/perfis/dados pessoais do usuário.
3. Preservar backend legado temporariamente para comparação. Novas opções de
   CLI/motor são propostas: só documentar como disponíveis após implementação.
4. Rodar os comandos existentes adequados a cada mudança:

```powershell
uv run python -m unittest discover -s tests
uv run ruff check
uv run python main.py --self-test
uv run python -m evals.runner --pilot --dry-run
```

Os dois últimos são smoke/dry-run, não prova de execução de tarefas. Testes GUI
seguem exclusivamente `scripts/Invoke-SandboxTest.ps1` e o guia Sandbox; não
usar `config.sandbox.json` no host. Novos runners de probe/aceitação precisam ser
implementados, documentados e protegidos contra inputs acidentais no host.

Logs devem correlacionar run/decisão/ação/observação/frame, proposta rejeitada,
motivo, modelo exato, tempo inclusive de vetos, resultado e ajuda humana. Guardar
capturas/prompts completos só em diagnóstico explícito, com retenção definida;
fixtures e relatórios versionados sanitizados. Não atribuir contagens globais
de GPU ao processo sem evidência.

## 9. Checklist vigente

- [x] R0: diagnóstico reproduzível e avaliação corrigida (20/09; ver
  `docs/relatorio-r0-r3-2026-09-20.md`).
- [ ] R1: memória/contratos/conclusão integrados ao loop real.
- [ ] R2: conteúdo visual/UIA e confirmação específica dos efeitos.
- [ ] R3: modelos e base selecionados por evidência, ou inviabilidade reportada.
- [ ] R4: execução genérica no Sandbox com resultados corretos.
- [ ] R5: aceitação em 6 GB, sem confundir ajuda/dry-run com autonomia.
- [ ] R6: entrega, documentação e remoção do legado desnecessário.

Não marcar uma etapa concluída enquanto houver gate não executado. Atualizar
este checklist com data, evidências e limitações, sem apagar resultados negativos.
