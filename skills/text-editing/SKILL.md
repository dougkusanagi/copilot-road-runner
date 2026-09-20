# text-editing

Edição com Unicode real (acentos nunca descartados).

- `type` usa SendInput Unicode; `ctrl+a` seleciona, `ctrl+c/v/x/z/s`
  recortam/ salvam. Confirmar: valor visível no campo focado
  ("text visible in focused field"); arquivo: ler de volta.
- Nunca repetir escrita não idempotente sem observar antes.
- Exemplo PT-BR: "digite 'Olá, não é ASCII — 100%' e salve" → type_text,
  verify com acentos intactos, `ctrl+s`, done com path como evidência.
