# copilot-road-runner — Computer Use local MVP (Windows)

Fluxo: instrução → tools determinísticas → UIA (`pywinauto`) → scorer por regras → fallback VLM (LM Studio) → `pyautogui` → observa → repete.

## Setup

```bash
uv sync
```

Requer **LM Studio** rodando com um modelo **vision** carregado (ex: `qwen2-vl`, `llava-1.6`)
para o fallback VLM. Sem ele, use `--no-vlm` (só determinístico + UIA).

## Uso

```bash
# teste sem clicar em nada
uv run python main.py --self-test

# checar LM Studio
uv run python vlm.py

# listar elementos UIA visíveis
uv run python uia.py

# demo browser + busca (end-to-end)
uv run python main.py "abra o Edge e busque preço RTX 4060" --max-steps 8

# sem VLM (só bootstrap determinístico + UIA)
uv run python main.py "abra o Edge e busque preço RTX 4060" --no-vlm --max-steps 4
```

## Segurança

- Pressione **ESC** para abortar o loop.
- Failsafe do `pyautogui`: encoste o mouse no canto superior-esquerdo.
- Log de cada passo em `run.jsonl` + screenshot em `last.png`.
