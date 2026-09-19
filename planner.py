"""Planner: MiniCPM5-1B (openbmb/MiniCPM5-1B). SÓ pensa — nunca vê screenshots.

Notas do model card oficial (verificadas antes de implementar):
- Arquitetura LlamaForCausalLM padrão → GGUF oficial (MiniCPM5-1B-GGUF:
  Q4_K_M 657MB / Q8_0 1.1GB) roda em llama.cpp, Ollama, LM Studio.
- Modos Think / No-Think no mesmo checkpoint; No-Think (temp 0.7, top_p 0.95)
  é o rápido — aqui usamos temp ainda menor (0.1) p/ saída determinística.
- Tool calling nativo do modelo é XML-style via parser SGLang (`minicpm5`).
  Via llama-server OpenAI-compatible NÃO há esse parser, então NÃO usamos o
  parâmetro `tools`: o planner responde um único objeto JSON (schema abaixo)
  e o Python valida + executa. Nada inventado no template de chat.

O planner recebe SÓ texto compacto (goal, janela, elementos, últimas ações,
último erro, tools). Ele NUNCA recebe screenshots e NUNCA emite coordenadas.
"""
from __future__ import annotations

import json
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, field_validator

PlannerActionType = Literal[
    "open_app", "open_url", "focus_window", "type_text", "press_key",
    "hotkey", "uia_click", "visual_action", "wait", "done",
]

# Tools que o planner pode escolher. uia_click = clicar por NOME acessível
# (Python resolve via UIA; se não achar, escala p/ visual_action sozinho).
# visual_action = "preciso enxergar" → screenshot vai SÓ p/ o Vocaela.
TOOLS_SPEC = """\
- {"type":"open_app","app":"notepad|calc|msedge|chrome|brave"} — abrir aplicativo
- {"type":"open_url","url":"https://..."} — abrir URL no Edge
- {"type":"focus_window","target":"trecho do título"} — focar janela
- {"type":"type_text","text":"..."} — digitar na janela focada
- {"type":"press_key","key":"enter|esc|tab|f5"} — uma tecla
- {"type":"hotkey","keys":"ctrl+n|ctrl+l|..."} — combinação
- {"type":"uia_click","target":"nome do elemento"} — clicar elemento VISÍVEL na árvore de acessibilidade (prefira sempre que o elemento tiver nome, ex: botão "7" da calculadora)
- {"type":"visual_action","instruction":"Click the blue Continue button"} — SÓ quando o elemento NÃO está na lista de UI elements (canvas, custom UI, ícone sem nome). Instruction em inglês, curta, com verbo + alvo. NUNCA inclua coordenadas.
- {"type":"wait","ms":2000} — aguardar UI carregar
- {"type":"done"} — objetivo cumprido"""

PLANNER_SYSTEM = """You are the planner of a local Windows computer-use agent. Think fast, output little.
Reply with EXACTLY ONE JSON object, no markdown, no explanation, no thinking trace.

Available actions:
""" + TOOLS_SPEC + """

Rules:
- NEVER output coordinates (no x, y). You do not see the screen.
- Prefer native tools (open_app, focus_window, type_text) over visual_action.
- If the current window is NOT the target app, use focus_window (NOT open_app again).
- NEVER repeat the same action twice in a row; if it did not advance, do something else.
- Prefer uia_click when the target name appears in UI elements.
- Use visual_action ONLY when the element is missing from UI elements.
- Say "done" ONLY if recent actions cover EVERY part of the goal
  (e.g., a goal that asks to write text REQUIRES a type_text in recent actions).
- Output ONLY the JSON object."""


class PlannerDecision(BaseModel):
    type: PlannerActionType
    app: str | None = None
    url: str | None = None
    target: str | None = None
    text: str | None = None
    key: str | None = None
    keys: str | None = None
    instruction: str | None = None
    ms: int = 0

    @field_validator("type")
    @classmethod
    def _no_coords_type(cls, v: str) -> str:
        return v

    def assert_no_coords(self, raw: dict) -> None:
        if any(k in raw for k in ("x", "y", "coordinate", "bbox", "bbox_2d")):
            raise ValueError(f"planner emitiu coordenadas (proibido): {raw}")


def build_prompt(goal: str, window: str, ui_names: list[str],
                 history: list[str], last_error: str = "") -> str:
    """Contexto compacto p/ o planner. Sem screenshots, sem árvore completa."""
    names = ", ".join(ui_names[:40]) or "(nenhum elemento exposto)"
    hist = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(history[-5:])) or "(nenhuma)"
    err = f"\nLast error:\n{last_error}\n" if last_error else ""
    return (f"Goal:\n{goal}\n\nCurrent window:\n{window or '(desconhecida)'}\n\n"
            f"Current UI elements:\n{names}\n\nRecent actions:\n{hist}\n{err}\n"
            f"Choose the next action.")


def extract_json(text: str) -> dict:
    """Extrai UM objeto JSON mesmo com fences/noise ao redor. Erro se inválido."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t).strip()
    try:
        d = json.loads(t)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    m = re.search(r"\{[^{}]*\}", t, re.DOTALL)
    if m:
        d = json.loads(m.group(0))
        if isinstance(d, dict):
            return d
    raise ValueError(f"planner não retornou JSON válido: {text[:200]!r}")


class MiniCPMPlanner:
    """Cliente fino do planner via endpoint OpenAI-compatible (/chat/completions)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8091/v1",
                 model: str = "MiniCPM5-1B", temperature: float = 0.1,
                 timeout_s: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s

    def check(self) -> dict:
        try:
            r = httpx.get(f"{self.base_url}/models", timeout=10.0)
            r.raise_for_status()
            data = r.json()
            return {"ok": True,
                    "models": [m.get("id", "?") for m in data.get("data", [])]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def next_action(self, goal: str, window: str, ui_names: list[str],
                    history: list[str], last_error: str = "") -> tuple[PlannerDecision, float]:
        """Uma decisão do planner. Retorna (decisão, planner_ms). Só texto."""
        user = build_prompt(goal, window, ui_names, history, last_error)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            # reasoning hibrido do MiniCPM5: modo rapido (sem thinking);
            # thinking consome tokens/latencia sem ajudar em decisao curta.
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 256,
        }
        t0 = time.perf_counter()
        with httpx.Client(timeout=self.timeout_s) as c:
            r = c.post(f"{self.base_url}/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
        ms = (time.perf_counter() - t0) * 1000
        content = data["choices"][0]["message"]["content"]
        raw = extract_json(content)
        dec = PlannerDecision.model_validate(raw)
        dec.assert_no_coords(raw)
        return dec, ms
