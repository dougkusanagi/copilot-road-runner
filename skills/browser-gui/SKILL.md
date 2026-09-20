# browser-gui

Navegação web PELA UI, como humano. Sem teleporte p/ URL.

1. `open_app` do navegador (ou `focus` se já aberto; o bootstrap prefere
   focar a janela existente — ela já está no perfil certo).
2. Hotkeys do browser (não invente combinações — errada não faz nada):
   `ctrl+t` nova aba, `ctrl+l` barra de endereço, `ctrl+w` fechar aba,
   `ctrl+Tab` alternar aba, `enter` confirmar. Ex.: nova aba + site =
   `sequence(ctrl+t, ctrl+l, type homepage, enter)`.
1b. Seletor de perfil ("Quem está usando o Chrome?", "Modo visitante"):
   NÃO adivinhe entre perfis de pessoas. Se há preferência lembrada, ela
   é aplicada sozinha; senão use `ask` UMA vez ("qual perfil devo usar?")
   e siga a resposta (ela será lembrada). Só sem humano por perto clique
   no primeiro perfil.
2. `ctrl+l`, digitar a HOMEPAGE conhecida, `enter`.
3. Na página: busca/formulário por `uia_click`/`type` + `enter`.
4. Perdido ou página de erro: voltar à homepage ou buscar no Google.
   NUNCA digitar subpath profundo adivinhado (`/produto-x-y/`).

- Abas: `ctrl+t`/`ctrl+Tab`; modal fecha com `esc`; carregamento lento =
  espera condicional (não sleep fixo).
- Exemplo PT-BR: "abra o Edge e busque o preço da RTX 4060" → open(edge),
  ctrl+l, type(homepage), enter, type(RTX 4060)+enter, answer(preço), done.
