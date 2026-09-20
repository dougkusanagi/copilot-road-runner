# Plano vigente — computer use local para GPUs a partir de 6 GB

Data: 19/09/2026. Status: **planejado; implementação ainda não iniciada**.

Este é o plano de evolução vigente. Substitui as propostas e prioridades da
[revisão de 18/09](revisao-codebase-2026-09-18.md), preservada como histórico.
[AGENTS.md](../AGENTS.md) distingue diretrizes futuras da implementação atual.
O [guia Sandbox](sandbox-test-env.md) continua sendo o procedimento operacional
de testes. Nenhum comando ou módulo marcado como proposto abaixo existe ainda.

## 1. Objetivo e limites

Construir um operador local rápido, capaz de entender pedidos em PT-BR, perceber
monitores/janelas e agir por clique, arraste, rolagem e digitação como uma pessoa.
Priorizar tarefas concluídas corretamente por unidade de tempo; tokens/s e
tamanho dos pesos são métricas auxiliares. Não prometer autonomia humana geral.

- Hardware mínimo-alvo: GPU com 6 GB de VRAM; registrar GPU, driver, backend,
  RAM, CPU, resolução e carga de outros aplicativos em cada benchmark.
- Operação normal inteiramente local após os downloads iniciais. Nenhum flagship
  ou API externa obrigatório. Manter instalação/runtime próprios e CLI simples.
- Evoluir incrementalmente: reaproveitar executor, Unicode, captura, safety,
  UI opcional, STT, runtime e Sandbox. Não reescrever tudo de uma vez.
- Python coleta fatos, transforma coordenadas, valida contratos, executa ações
  escolhidas pelo modelo e veta ações inválidas. Não interpreta palavras-chave
  do pedido para escolher estratégias ou concluir tarefas.
- No modo GUI padrão, acessibilidade serve para observar e localizar; a ação usa
  mouse/teclado reais, com foco validado. Não copiar o padrão do ZCode de edição
  semântica invisível em segundo plano. Navegação continua pela UI, sem open_url.
- Skills podem oferecer CLI/scripts explícitos (ex.: Blender), selecionados pelo
  modelo, com ferramentas e argumentos delimitados. Essa capacidade é separada
  do modo GUI e identificada no log; não é fallback oculto.
- FAILSAFE e hotkey ctrl+alt+esc permanecem. Um único executor pode controlar
  mouse/teclado por vez; cancelamento libera teclas/botões pressionados.

## 2. Diagnóstico que motiva a refatoração

O código atual usa MiniCPM5-1B textual + Vocaela-2-500M. O planner vê até 40
nomes e cinco ações recentes; resolução por nome pode ser ambígua. Não há estado
persistente de subtarefas. A percepção global dos monitores e a compreensão de
conteúdo visual são insuficientes. Verify coleta UIA que pode ser coletada outra
vez no passo seguinte; esperas de 500 ms + 300 ms acumulam custo fixo. Confianças
0,9/0,8 preenchidas pelo código não são probabilidades do modelo.

O run.jsonl examinado mostrou primeira decisão em ~4,26 s, seguintes em
~0,66–0,72 s e repetição de open_app(chrome) sem progresso. É uma amostra, não um
benchmark nem prova da causa. Não trocar modelos e arquitetura ao mesmo tempo
sem preservar uma referência reproduzível.

## 3. Matriz de modelos e ordem dos experimentos

Todos os perfis são candidatos, não promessas de caber ou responder em 6 GB.
Começar com quantização Q4 compatível, contexto limitado e uma imagem por vez;
comparar Q5/Q8 apenas se houver memória e ganho mensurável. Fixar revisão, hash,
template, projetor, versão do runtime e parâmetros por perfil.

| ID | Planner | Visão | Objetivo / prioridade |
|---|---|---|---|
| B0 | MiniCPM5-1B | Vocaela-2-500M-1024R2 | Baseline atual, obrigatório |
| B1 | MiniCPM5-2B | Mesmo Vocaela | Isolar efeito da troca 1B → 2B |
| D1 | MiniCPM5-2B | Qwen3-VL-2B-Instruct | Dois modelos: planejamento textual + percepção/ação visual geral |
| D2 | MiniCPM5-2B | Qwen3.5-2B | Comparar visão geral mais recente com D1 |
| U1 | Qwen3.5-2B único | Mesmo processo/modelo | Menor perfil unificado, referência multimodal oficial |
| U2 | Qwen3.5-4B único | Mesmo processo/modelo | Qualidade com um único conjunto de pesos; hipótese para 6 GB |
| G1 | MiniCPM5-2B | GUI-Owl-1.5-2B-Instruct | Opcional: especialista GUI, comparar com vencedor D1/D2 |
| E1 | Empero Qwen3.8-2B-Distill | Vocaela ou visão vencedora | Opcional: avaliar como planner textual |
| E2 | Empero Qwen3.8-2B-Distill único | A validar | Só se artefato multimodal completo passar no teste de capacidade |

Ordem: B0 → B1 → U1/D1/D2 → U2 → G1/E1/E2 se os testes anteriores justificarem.
Não executar todos simultaneamente nem adicionar um terceiro modelo ao caminho
obrigatório. Preservar Vocaela como baseline; um VLM geral pode entender melhor
e ainda clicar pior. Comparar compreensão e localização separadamente.

### 3.1 O “Qwen3.8-2B” da imagem

O artefato indicado é `empero-ai/Qwen3.8-2B-Distill-GGUF`, não uma publicação
oficial `Qwen/Qwen3.8-2B`. O autor descreve destilação textual sobre Qwen3.5-2B,
visão herdada não avaliada e respostas com raciocínio. A árvore GGUF consultada
não lista mmproj. Nome mais recente não demonstra melhor visão nem menor latência.
Não conectar um projetor da base por suposição: conferir compatibilidade e
testar imagens diferentes com texto idêntico para detectar imagem ignorada.
Se só texto funcionar, E1 permanece elegível; E2 fica indisponível com motivo.
Não tomar presença de tag multimodal ou exemplo automático do Hugging Face como
prova de funcionamento no runtime Windows. Não supor que enable_thinking=false
funciona nessa destilação: medir geração, formato e qualidade do modo curto.

### 3.2 Teste de capacidade antes de baixar/rodar a bateria

- Conferir licença, origem, revisão, arquitetura, tokenizer/chat template,
  pesos visuais/projetor e suporte exato no llama.cpp Windows usado pelo projeto.
- Testar: JSON restrito, Unicode PT-BR, leitura de texto na tela, interpretação
  de diálogo, localização de alvo, distinção entre duas imagens e alvo ausente.
- Medir cold start, primeira inferência e execução aquecida separadamente.
- Backend CUDA/Vulkan conforme GPU e build testado; não presumir que ngl>0 num
  binário CPU habilita GPU. Mostrar offload efetivo e memória dedicada/compartilhada.
- Sem suporte, OOM ou limite excedido: marcar perfil inelegível; não converter
  falha em teste aprovado com CPU/offload parcial silencioso.

## 4. Arquitetura alvo

Fluxo comum: pedido → observação → decisão do modelo → validação → execução →
observação do efeito → atualização da tarefa → próxima decisão.

**Perfil duplo:** planner textual escolhe ação UIA/teclado, solicitação de
percepção visual ou instrução visual específica. O VLM recebe imagem e devolve
fatos com evidência ou ação visual. Fatos voltam ao planner quando a interpretação
da tarefa exigir; ação visual já delimitada pode ir ao executor sem mais uma
chamada de aprovação. Planner textual continua sem screenshots/coordenadas.

**Perfil unificado:** o mesmo VLM recebe texto ou texto+imagem e pode planejar,
interpretar e apontar. Uma chamada pode produzir ação e atualização compacta da
tarefa. Screenshot só quando necessário. Usa schema próprio com referência de
frame; a restrição “planner nunca vê imagens” vale só para o perfil textual.

Os dois perfis compartilham contratos, memória, executor, evidências e avaliação.
O modelo escolhe quando precisa de mais percepção ou de uma skill; política
determinística limita orçamento e recusa pedidos impossíveis, sem escolher alvo.

### 4.1 Contratos propostos

| Contrato | Campos/responsabilidades principais |
|---|---|
| Observation | observation_id, timestamp, monitores, app/PID/HWND, foco, modal, UIA, delta, cobertura/truncamento |
| ElementRef | observation_id + element_id; papel, nome, contexto ancestral, valor/estado, bounds; IDs não reutilizados entre snapshots |
| FrameRef | frame_id, observation_id, monitor/janela, origem, escala/DPI, dimensões, instante da captura |
| TaskState | objetivo, subobjetivo, pendências/concluídas, evidências, fatos, falhas recentes, skill ativa |
| Decision | ação/percepção/skill/conclusão, argumentos tipados, referências, efeito esperado, atualização compacta de TaskState |
| ActionResult | action_id, sent=true/false/unknown, resultado confirmado/não confirmado, evidências, erro, post_state |
| Completion | referência às evidências que cobrem os requisitos; sucesso/parcial/bloqueado/cancelado |

Schemas discriminados por tipo de ação, sem campos irrelevantes preenchidos com
null. Validar também no Python: JSON válido não garante decisão correta. Não
aceitar confidence fixa como certeza; deixar ausente quando não calibrada.

### 4.2 Observação global e visão seletiva

- Enumerar monitores, posições negativas, DPI, janelas, z-order/oclusão, foco e
  modais; ignorar overlays próprios. Não escolher janela por “primeira da lista”.
- Snapshot UIA compacto com papel, nome, estado habilitado/visível, valor, contexto
  e ID. Reservar espaço para texto/conteúdo, não só controles. Informar cortes e
  permitir ao modelo pedir expansão de ramo/região; ausência em lista truncada
  não significa inexistência na UIA.
- Avaliar CacheRequest/TreeWalker ou coleta em lote; limites reais de duração
  para providers COM travados. Worker isolado/cancelável se necessário.
- Reutilizar post_state enquanto válido; invalidar em escrita, troca de janela,
  modal, rolagem ou evento relevante. Evento ausente não prova estado inalterado.
- OCR local opcional para texto não exposto; medir benefício contra custo. VLM
  interpreta layout, diálogos e conteúdo visual. OCR não substitui compreensão.
- Visão global reduzida sob demanda; recorte detalhado da janela/região/monitor
  solicitado pelo modelo. Evitar mosaico de monitores que destrói texto pequeno.
- Coordenadas vinculadas ao frame. Python transforma frame→desktop virtual uma
  única vez. Recorte/zoom tem transformação explícita; nunca reaproveitar pixels
  de imagem velha ou misturar bounds UIA com pixels redimensionados.

### 4.3 Execução, verificação e recuperação

- Resolver alvos UIA por ID da observação, não fuzzy matching de nomes. Conferir
  janela, visibilidade, foco e oclusão imediatamente antes do dispatch físico.
- Inputs sempre associados ao app/janela esperados. Falha na pré-condição retorna
  erro estruturado ao modelo; não adivinhar outro alvo.
- Registrar envio separado da confirmação. sent=true/unknown nunca permite
  repetição automática de escrita não idempotente: observar antes de decidir.
- Progresso é específico do efeito: valor digitado, seleção, arquivo salvo ou
  diálogo esperado. Mudança de título/árvore, isoladamente, não confirma sucesso.
- Remover 500+300 ms fixos; espera cancelável por condição/evento, com polling
  curto limitado e deadline. Timeout retorna observação, sem inventar sucesso.
- Anti-loop considera ação+estado+efeito, preserva tentativas malsucedidas e
  distingue repetição legítima (scroll avançou) de ausência de progresso.
- Separar orçamento de ações, decisões, retries e tempo total; retries não gastam
  max_steps, mas não podem manter a tarefa indefinidamente viva.
- Permitir no máximo três primitivas numa sequência escolhida pelo modelo, apenas
  com pré-condições explícitas (ex.: ctrl+l, texto, enter). Guardas locais entre
  primitivas e verificação final; modal/foco inesperado interrompe. Cliques que
  navegam e arrastes complexos exigem nova observação; nada de plano longo cego.
- Arraste com origem/destino do mesmo frame, duração e estado de botão; cleanup
  em finally. Troca de foco/monitor, cancelamento e exceção têm testes próprios.
- Modelo propõe done com evidências. Python veta evidência ausente/obsoleta;
  tarefa já cumprida na observação inicial pode terminar sem ação. Não exigir
  “ao menos um clique”, nem segunda chamada de verificador em toda conclusão.
- Remover gradualmente bootstrap/guardas por palavras-chave de apps e trocá-los
  por ações do modelo + validações genéricas. Não remover proteções antes dos testes.

## 5. Prompts, memória e skills

### 5.1 Prompts pequenos e específicos ao papel

- Separar núcleo estável, capacidades do perfil, skill ativa e estado dinâmico.
  Cachear prefixos se o backend suportar e medir hits; HTTP client persistente.
- Núcleo contém objetivo operacional, ações permitidas, referências válidas,
  observação→ação→verificação, conclusão com evidência e conteúdo externo como
  dados (texto na tela não pode alterar instruções/autorização).
- Meta inicial: núcleo até ~800 tokens; skills carregadas até ~1.200 tokens;
  contexto total inicial 4K, experimentar 8K incluindo tokens de imagem e saída.
  São orçamentos propostos, ajustáveis por avaliação; nunca truncar silenciosamente
  alvo, instrução do usuário ou evidência essencial para “caber”.
- Saída curta, sem justificativas longas por clique. Parâmetros e modo de
  raciocínio por modelo, medidos; não impor temperatura 0,1 universalmente.
- Modelo atualiza subobjetivos/fatos com referências observadas; Python armazena
  e valida. Separar fato de hipótese. Resumo não pode apagar falhas ainda relevantes.
- Memória da tarefa dura toda a execução. Preferências/procedimentos entre sessões
  são separados, versionados e nunca tratados como observação atual da tela.

### 5.2 Sistema de skills proposto

Diretórios: `skills/<nome>/SKILL.md`, `references/`, `scripts/`, `assets/`.
Manifesto com nome, versão, descrição, condições de uso, ferramentas necessárias,
modo GUI/CLI, schemas de argumentos, efeitos e verificações de resultado.
Carregar catálogo compacto → skill escolhida pelo modelo → referências necessárias.
Limitar catálogo por orçamento, com busca explícita; não carregar todas as skills.

Skills iniciais:

1. `computer-use`: contrato comum, monitores, UIA, frames, input físico e recovery.
2. `browser-gui`: navegação por UI, abas, carregamento e formulários; sem teleporte.
3. `text-editing`: Unicode, seleção, salvar e confirmar conteúdo/arquivo.
4. `blender-cli`: criação de cenas/objetos simples por scripts parametrizados,
   exportação e render de verificação; piloto opcional após estabilizar GUI.

No Blender, modelo escolhe receita/argumentos; script implementa operação limitada.
Executar subprocess com argv, sem shell=True, cwd delimitado, timeout e cancelamento;
validar paths/argumentos e conservar stdout/stderr/artefatos. Nunca abrir execução
arbitrária de shell como efeito colateral de instalar skill. Scripts novos não
ganham confiança só por estarem num SKILL.md. Não confundir receita parametrizada
com capacidade de criar qualquer cena complexa. Validar o artefato e imagem renderizada.

Testar ativação correta, não ativação, casos ambíguos e dependência ausente; incluir
exemplos realistas PT-BR. Não repetir chamadas técnicas de descoberta por ação:
catálogo e schemas vivem no executor. Sem subagentes controlando o mesmo desktop.

## 6. Lições do ZCode 3.9.1 inspecionado localmente

Referência: `C:/Program Files/ZCode/resources/glm/zcode.cjs` (montagem modular do
contexto) e `packages/` sob a mesma pasta: `zcode-cua-plugin/skills/zcode-computer-use`,
`browser-use-plugin/skills/control-browser`, `browser-use-plugin/skills/web-gui-tester`,
`skill-creator-plugin/skills/skill-creator` e `document-skills-plugin/skills/docx`.
Foi lido código/instruções distribuídos; não foi capturado prompt final de sessão.

Adotar os princípios: observação barata suficiente, referências vinculadas ao
estado/frame, post_state compacto, confirmação específica e skills sob demanda.
Não copiar textos extensos, fluxo de agente de programação, 30 ferramentas por
prompt, bootstrap JavaScript por chamada ou ação semântica em background.
No nosso executor, transforms/capacidades/timeout ficam implementados e testados;
não pedir que um modelo de 2B reaprenda detalhes de plataforma em cada ação.

## 7. Runtime e orçamento de 6 GB

- Configuração tipada por perfil e capacidade (`text`, `vision`, `grounding`,
  `structured_output`), separada de nomes fixos de modelos. Um perfil unificado
  usa um processo; não carregar o mesmo checkpoint duas vezes.
- Preservar download/reuso local; manifestos fixam hashes de pesos, projetor e
  binário. Endpoint vivo só é reutilizado se modelo/capacidade forem compatíveis.
- Reservar como meta inicial pelo menos 1 GB para desktop/apps: pico incremental
  do agente até ~5 GB na placa de 6 GB, incluindo KV, encoder e buffers. Medir
  memória total e baseline dos apps; Blender pode exigir reserva maior.
- Uma geração ativa por GPU inicialmente; filas curtas e cancelamento. Não
  paralelizar duas inferências pesadas por princípio. STT em CPU inicialmente.
- Contexto 4K/8K; screenshot da região necessária, orçamento de pixels/tokens
  registrado. Resolução menor não pode tornar texto/alvo ilegível sem sinalizar.
- Warmup pequeno, conexão reutilizada, cancelamento de HTTP, limites separados
  para carga, prefill e geração; retries de inferência não repetem ações físicas.
- Manter perfis residentes se couberem; se precisar descarregar/carregar a cada
  clique, medir esse custo e preferir perfil menor/unificado se vencer.
- Fallback CPU pode ser opção explícita de instalação, nunca benchmark de GPU
  disfarçado. Se orçamento/capacidade falhar, reportar motivo e perfil utilizável.

## 8. Entregas sequenciais e critérios de aceite

Cada fase gera commit testável, suite/lint verdes e atualização de status aqui.
Todos os itens abaixo estão pendentes. Começar pela F0; não trocar o default antes
da F7. Nomes de arquivos novos são propostas, evitando um framework desnecessário.

| Fase | Escopo e arquivos | Critério de aceite |
|---|---|---|
| F0 | `evals/tasks.json`, runner, `telemetry.py`, `loop.py`; logs por run | Baseline B0 reproduzível; falhas/tempos/ambiente registrados; sem clicar no host |
| F1 | `schemas.py`, `config.py`, `state.py`; adaptar interfaces atuais | Observation/TaskState/ActionResult tipados, compatibilidade B0, confianças fictícias removidas |
| F2 | `uia.py`, `obs.py`, `actions.py`, `safety.py` | Alvos por ID/frame; testes DPI, monitor negativo, stale state, foco e cleanup; coleta reaproveitada |
| F3 | `planner.py`, `loop.py`, `verification.py`, prompts por papel | Memória, conclusão por evidências, espera condicional, anti-loop com progresso; guards genéricos |
| F4 | `model_adapters.py`, `server.py`, `config.py`, `vocaela.py` | Perfis B1/D/U intercambiáveis, capability smoke tests, GPU real e orçamento medidos |
| F5 | `skills.py`, `skills/`; executor CLI restrito | Carregamento progressivo; três skills GUI; piloto Blender em ambiente descartável separado |
| F6 | `loop.py`, runtime/observação | Sequências até 3 primitivas, cache/pooling e cancelamento; benefício por ablação sem regressão |
| F7 | Matriz de avaliação e relatório em docs | Escolha de default com evidências; rollback B0/B1; README/AGENTS sincronizados |

Dependências: F1→F2→F3; F4 requer F1/F2 e usa F0; F5 requer F3; F6 após contratos
estáveis; F7 integra todas. Começar F4 pelos smoke tests baratos antes de investir
em ajustes específicos de um modelo. Cada fase mantém uma configuração funcional.

Checklist de acompanhamento:

- [ ] F0 baseline e telemetria.
- [ ] F1 contratos e estado.
- [ ] F2 observação e execução vinculadas.
- [ ] F3 memória, prompts e verificação.
- [ ] F4 perfis e viabilidade de 6 GB.
- [ ] F5 skills e piloto Blender.
- [ ] F6 otimização medida.
- [ ] F7 comparação final, default e documentação.

## 9. Avaliação e condições para promover um perfil

### 9.1 Infraestrutura e métricas

Usar os scripts existentes do Windows Sandbox. Modelos ficam no host/GPU;
cliques ficam no Sandbox. Não passar config.sandbox.json no host. Replay de
observações é diagnóstico offline, não prova de sucesso end-to-end. Dry-run
proposto bloqueia TODOS os efeitos (inclusive bootstrap, foco, teclado e CLI).

Criar `runs/<id>/` gitignored com JSONL, summary, configuração/revisões, timings,
decisões e evidências. Capturas/prompts completos só em modo diagnóstico explícito,
com retenção/limpeza; não versionar conteúdo privado nem credenciais. Não apagar
o run anterior. Logar renderização do contexto e contagens de tokens/pixels.

Medir sucesso por checker independente, falso done, passos, retries, ausência de
progresso, chamadas por modelo, UIA/OCR/captura/prefill/geração/execução/verificação,
TTFT, p50/p95 de decisão e de tarefa, carga inicial e memória dedicada/compartilhada.
Registrar tempo das falhas e taxa de timeout; não esconder falhas na média dos sucessos.

### 9.2 Bateria inicial

20 tarefas determinísticas, cinco repetições por candidato finalista (100 runs):

- 4 de Notepad/edição: acentos, seleção/substituição, salvar, pedido já cumprido.
- 3 de calculadora: entrada, correção de estado existente, resultado verificado.
- 5 em página local fixture: busca, formulário, aba nova, modal e carregamento lento.
- 4 visuais: canvas sem UIA, arrastar/soltar, ícone pequeno com crop, ler erro visual.
- 4 de recuperação: alvo inexistente, nomes duplicados, foco alterado, ação enviada
  com confirmação atrasada (não duplicar).

Checkers podem ler estado interno/arquivos das fixtures para avaliar; o agente
nunca recebe o gabarito nem usa esse acesso para concluir a tarefa. Separar casos
de desenvolvimento e holdout (novos nomes/layouts) para evitar ajuste ao teste.
Piloto inicial: uma repetição de cinco tarefas por perfil; eliminar incapazes
antes da bateria completa. Depois ampliar com tarefas reais controladas.

Multi-monitor/DPI: testes unitários de transforms + fixtures de screenshots e
smoke manual em máquina de teste dedicada quando Sandbox não representar o caso.
Não contornar isolamento clicando no desktop de trabalho. Blender é uma bateria
separada, opcional, com instalação explícita no ambiente descartável.

### 9.3 Gates propostos (metas, não resultados já obtidos)

1. Zero violações observadas de janela/frame e zero inputs após cancelamento;
   testes de safety/cleanup obrigatórios. Zero falsos done na bateria inicial.
2. Pelo menos 90% de sucesso nas 20 tarefas delimitadas, reportando também por
   categoria. Esse número não implica 90% de sucesso em tarefas arbitrárias.
3. Sem OOM ou spill sustentado para memória compartilhada; atingir reserva de
   VRAM definida em §7 com desktop/apps abertos, em GPU física de 6 GB.
4. Para substituir default: não regredir sucesso e reduzir mediana do tempo em
   pelo menos 20%, OU ganhar ≥10 pontos percentuais de sucesso com aumento de
   p95 de tarefa de no máximo 25%. Publicar amostra/dispersão; repetir se diferença
   for inconclusiva. Comparar com B0 original e B0 no novo loop para separar efeitos.
5. Metas iniciais de latência aquecida: p95 decisão textual ≤1,5 s e visual ≤3 s,
   medidos do estado pronto à decisão validada. Não são promessa universal; se
   falharem, registrar gargalo e rever escopo/perfil antes de declarar pronto.

Ablações: 1B/2B, Vocaela/VLM, duplo/unificado, memória ligada/desligada,
sequência/ação única, observação reaproveitada/nova, Q4/Q5, contexto 4K/8K,
resolução e modo de raciocínio. Alterar um fator por vez nos finalistas.

### 9.4 Verificação de desenvolvimento

Suite oficial: `uv run python -m unittest discover -s tests`.
Lint: `uv run ruff check`. Smoke sem interação: `uv run python main.py --self-test`.
Mocks/fakes testam contratos, timeout, cancelamento, retries, efeitos desconhecidos,
conclusão inicial, stale frames, Unicode, OOM e skill ausente. Testes não podem
apenas espelhar texto de implementação; preferir comportamento e invariantes.
Testes com cliques só via scripts documentados no guia Sandbox; começar com
max_steps 4, aumentar por tarefa somente após smoke seguro.

## 10. Migração, itens adiados e manutenção

- Flags/perfis novos opt-in; manter config legado migrável e rollback testado.
  Atualizar `--self-test`, CLI, UI/tray e exemplos juntos ao promover um perfil.
- O runtime atual tem dois endpoints; unificado terá um serviço e aliases lógicos
  sem duplicar pesos. Atualizar bootstrap/Sandbox para o perfil escolhido.
- Jev: fora do caminho obrigatório local. Experimento futuro só se API externa
  for desejada; substituir uma decisão delimitada, não somar chamadas em série.
- Fine-tuning/distilação: depois de coletar trajetórias corretas revisadas,
  separar treino/holdout, avaliar generalização; não treinar automaticamente nos
  próprios erros ou usar um flagship em runtime como requisito escondido.
- Speculative decoding/draft extra e múltiplas inferências paralelas: adiar até
  medir gargalo de geração; podem piorar VRAM/latência em saídas curtas.
- Do roadmap antigo: incorporar config tipada, pooling, harness e logs neste plano.
  Cache de instalação do Sandbox e limpeza por retenção podem vir após F0.
  Reuso de Sandbox só explícito, por ID, nunca padrão de avaliação limpa; nunca
  encerrar instância alheia. LICENSE do projeto continua decisão do autor.
- Preservar quirks e correções já feitas. A revisão histórica não autoriza
  reintroduzir open_url, sleeps fixos ou conclusão sem evidência.

## 11. Fontes e rastreabilidade

Consultadas em 19/09/2026; model cards podem mudar. Fixar commits dos artefatos
na implementação; benchmarks dos autores não substituem a bateria local.

- [MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B)
- [Vocaela-2-500M](https://huggingface.co/vocaela/Vocaela-2-500M-1024R2)
- [Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)
- [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B)
- [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)
- [GUI-Owl-1.5-2B](https://huggingface.co/mPLUG/GUI-Owl-1.5-2B-Instruct)
- [Empero: card do modelo](https://huggingface.co/empero-ai/Qwen3.8-2B-Distill)
- [Empero: arquivos GGUF](https://huggingface.co/empero-ai/Qwen3.8-2B-Distill-GGUF/tree/main)
- [llama.cpp multimodal](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [ZCode: skills](https://zcode.z.ai/en/docs/skill)
- [Jev: perguntas tipadas](https://docs.typesafe.ai/introduction)
