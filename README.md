# copilot-road-runner — Computer Use local MVP (Windows)

Fluxo: instrução → planner MiniCPM5-1B (`:8091`, só texto, nunca recebe
screenshot, nunca emite coordenadas) → UIA por nome (`pywinauto`) →
Vocaela-2 (`:8082`, screenshot → ação visual 0..1, só quando o elemento
não está na accessibility tree) → `pyautogui` → observa → repete.
Python executa e NUNCA decide; sem modelos online = erro honesto.

## Setup

```bash
uv sync
```

Requer dois `llama-server` ouvindo na rede (`--host 0.0.0.0`):
planner MiniCPM5-1B em `:8091` + visão Vocaela-2 em `:8082`.
Detalhes do ambiente isolado em `docs/sandbox-test-env.md`.

## Uso

```bash
# teste sem clicar em nada
uv run python main.py --self-test

# suite oficial (sempre via uv)
uv run python -m unittest discover -s tests

# dry-run do grounding Vocaela (screenshot → ação, sem clicar)
uv run python main.py --locate "Click the address bar"

# end-to-end (comece com --max-steps 4; nunca no host enquanto usa o PC — use o Sandbox)
uv run python main.py "abra o Edge e busque preço RTX 4060" --max-steps 4
uv run python main.py "..." --config config.sandbox.json --max-steps 4
```

## Segurança

- Pressione **ESC** para abortar o loop.
- Failsafe do `pyautogui`: encoste o mouse no canto superior-esquerdo.
- Log de cada passo em `run.jsonl` + screenshot em `last.png`.
