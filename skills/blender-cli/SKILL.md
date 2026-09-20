# blender-cli (piloto opcional)

Criação de cenas SIMPLES por receitas parametrizadas — não "qualquer cena
complexa". O modelo escolhe receita/argumentos; o script implementa a
operação limitada. Separado do modo GUI e identificado no log; nunca
fallback oculto, nunca shell arbitrário.

- Receitas: `cubo`, `esfera` (parâmetros: `tamanho`). Scripts em
  `scripts/`; executados com argv, sem shell, cwd em `blender-jobs/`,
  timeout e cancelamento; stdout/stderr/artefatos conservados.
- Blender precisa estar instalado NO AMBIENTE DESCARTÁVEL (nunca no
  desktop de trabalho); dependência ausente = erro honesto.
- Verificação: `.blend` + PNG renderizado existem e a imagem é validada.
- Exemplo PT-BR: "crie um cubo no Blender" → use_skill(blender-cli,
  {recipe: cubo, tamanho: 2}) → render `cubo.png` → done com artefato.

Scripts novos NÃO ganham confiança só por estarem aqui: validar o artefato
e a imagem renderizada antes de concluir.
