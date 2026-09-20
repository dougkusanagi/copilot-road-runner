# copilot-road-runner — Computer Use local MVP (Windows)

> Este README descreve a implementação atual. A evolução para GPUs a partir de
> 6 GB, skills e comparação de modelos está no
> [plano vigente de refatoração](docs/plano-refatoracao-2026-09-19.md)
> (planejado, ainda não implementado).

Fluxo: instrução → planner MiniCPM5-1B (`:8091`, só texto, nunca recebe
screenshot, nunca emite coordenadas) → UIA por nome (`pywinauto`) →
Vocaela-2 (`:8082`, screenshot → ação visual 0..1, só quando o elemento
não está na accessibility tree) → `pyautogui` → observa → repete.
Python executa, observa e **veta** (guard-rails: bootstrap da janela do app,
anti-janela-errada, anti-repetição, coordenadas fora da tela) mas nunca
escolhe a ação; sem modelos online = erro honesto.

## Setup

```bash
uv sync            # Python 3.12 (.python-version)
uv run ruff check  # lint (dev-deps)
```

Runtime próprio (sem depender de `llama-server` externo): na 1ª execução
o loop baixa o binário (`llama.cpp` Windows x64 CPU) + os GGUFs
(MiniCPM5-1B-Q4_K_M ~657 MB, Vocaela-2-Q8_0 + mmproj ~534 MB) para
`models/` (gitignored) e sobe planner em `:8091` + visão em `:8082` —
portas fora do padrão, sem conflito com Ollama (`11434`) nem LM Studio
(`1234`). Nas seguintes, só reusa. Endpoint já vivo na porta é
reaproveitado (não importa quem subiu); porta ocupada sem endpoint =
erro honesto. Desligue com `runtime.auto_start: false` ou `--no-runtime`;
`uv run python -m server` sobe os dois e fica no ar (`--host 0.0.0.0`
expõe ao Sandbox, só p/ testes).
Detalhes do ambiente isolado em `docs/sandbox-test-env.md`.

## Modelos (manual)

Normalmente você não precisa disso (`main.py` baixa e sobe sozinho).
Para subir na mão ou expor ao Sandbox:

```powershell
# planner MiniCPM5-1B em :8091 (--jinja: template oficial do MiniCPM5)
.\models\bin\llama-server.exe -m .\models\MiniCPM5-1B-Q4_K_M.gguf `
  --host 127.0.0.1 --port 8091 -c 4096 --jinja

# visão Vocaela-2 em :8082 (--mmproj obrigatório p/ imagem)
.\models\bin\llama-server.exe -m .\models\Vocaela-2-500M-1024R2-Q8_0.gguf `
  --mmproj .\models\mmproj-Vocaela-2-500M-1024R2-Q8_0.gguf `
  --host 127.0.0.1 --port 8082 -c 4096

# ou os dois de uma vez (fica no ar até Ctrl+C):
uv run python -m server
# p/ o Sandbox enxergar o host: --host 0.0.0.0 (+ config.sandbox.json → HOST_IP)
uv run python -m server --host 0.0.0.0
```

## Uso real (local, padrão — sem parâmetros)

O sistema roda **no host por padrão**, sem nenhum parâmetro: `config.json`
(`127.0.0.1:8091/8082`) já aponta para o runtime próprio.

```bash
# teste sem clicar em nada
uv run python main.py --self-test

# dry-run do grounding Vocaela (screenshot → ação, sem clicar)
uv run python main.py --locate "Click the address bar"

# end-to-end (comece com --max-steps 4; não use o PC enquanto roda)
uv run python main.py "abra o Edge e busque preço RTX 4060" --max-steps 4
```

```bash
# suite oficial (sempre via uv)
uv run python -m unittest discover -s tests
```

O Sandbox é **só para testes de desenvolvimento** e é acionado apenas
pelos scripts (`.\scripts\Start-Sandbox.ps1` manual,
`.\scripts\Invoke-SandboxTest.ps1` automatizado — detalhes em
`docs/sandbox-test-env.md`). Nunca passe `--config config.sandbox.json`
no host: esse arquivo só existe **dentro** do Sandbox (gerado pelo
`bootstrap.ps1` com o HOST_IP).

## Tray + janela Spotlight + ditado (opcional)

```bash
uv sync --extra ui          # pywebview, pystray, faster-whisper, sounddevice
uv run python main.py --ui  # ícone na bandeja; ctrl+alt+space mostra/esconde
```

Caixa de texto + **Enviar** + **microfone**: o texto aparece enquanto você fala
(faster-whisper `base` int8, ~74 MB, baixado na 1ª vez); durante a gravação há
**Parar** (texto fica na caixa para corrigir) e **Enviar**; silêncio de 1,5 s
envia sozinho (`stt.auto_send`). A janela se esconde enquanto o agente age.
Config em `config.json` → seções `ui` e `stt` (modelo `tiny|base|small`,
`silence_ms`, `hotkey`).

## Segurança

- Uso real roda no host: não use mouse/teclado enquanto o agente age.
  Pressione **Ctrl+Alt+Esc** (`stop_hotkey` no `config.json`) para abortar
  o loop; ESC puro não aborta (o agente pode usar `press_key esc`).
  Testes de desenvolvimento (cliques descartáveis) vão no Sandbox.
- Failsafe do `pyautogui`: encoste o mouse no canto superior-esquerdo.
- `open_app` só aceita apps da whitelist (`tools.APP_COMMANDS`).
  Não há teleporte p/ URL: o planner navega pela UI do navegador
  (`ctrl+l`, digitar, `enter`, cliques), como um humano.
  Nada que o planner emite passa por shell.
- Log de cada passo em `run.jsonl` + screenshot em `last.png`.
