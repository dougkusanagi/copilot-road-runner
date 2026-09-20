# computer-use

Contrato comum do modo GUI. Observar → decidir → validar → executar →
observar o efeito → atualizar a tarefa.

- Monitores: posições podem ser negativas; DPI por monitor; nunca escolher
  janela pela "primeira da lista"; overlays `crr-overlay` são ignorados.
- UIA: alvos por `observation_id#element_id` (IDs não reutilizados entre
  snapshots). Lista truncada: ausência NÃO prova inexistência — peça
  expansão de ramo/região.
- Frames: coordenadas 0..1 valem SÓ no `frame_id`; Python converte
  frame→desktop virtual uma única vez. Nunca reaproveitar pixels velhos.
- Input sempre na janela esperada; pré-condição falha = erro estruturado,
  sem adivinhar outro alvo. `sent=true/unknown` nunca repete escrita.
- Exemplo PT-BR: "abra o Bloco de Notas e digite Olá" → open_app(notepad),
  type_text("Olá"), verify com valor visível, done com evidência.
