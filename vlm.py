"""Visual fallback: VLM usado SÓ como grounding (screenshot + "locate X" → {x,y}).

Modelo default: MAI-UI-2B (config.json → vision_model).
Verificação de suporte (2026-09): MAI-UI-2B existe no HuggingFace
(Tongyi-MAI/MAI-UI-2B, Qwen3-VL, Apache-2.0) e em quants comunitárias no
Ollama (`maternion/mai-ui:2b`, ~2.6GB) — que expõe API OpenAI-compatible em
http://127.0.0.1:11434/v1. Suporte nativo em LM Studio/llama.cpp (GGUF)
não confirmado; regra do projeto: não travar nisso — a interface abaixo
funciona com QUALQUER servidor OpenAI-compatible + modelo vision
(qwen2-vl, llava, internvl2...). Troque só `base_url`/`vision_model`.

O controle do agente continua no Python; o VLM nunca decide ações.
"""
from __future__ import annotations

import json
import re

import httpx
from pydantic import BaseModel

from schemas import Action

DEFAULT_MODEL = "MAI-UI-2B"
TIMEOUT = 120.0


class GroundingResult(BaseModel):
    x: float  # 0..1 (normalizado pela largura da imagem enviada)
    y: float  # 0..1
    confidence: float = 0.5


class VisionModel:
    async def locate(self, screenshot, instruction: str) -> GroundingResult:
        raise NotImplementedError

    def locate_sync(self, screenshot_b64: str, instruction: str) -> GroundingResult:
        raise NotImplementedError


def check_server(base_url: str = "http://127.0.0.1:1234/v1") -> dict:
    """Retorna {'ok': True, 'models': [...]} ou {'ok': False, 'error': ...}."""
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/models", timeout=10.0)
        r.raise_for_status()
        data = r.json()
        models = [m.get("id", "?") for m in data.get("data", [])]
        return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e)}


check_lmstudio = check_server  # alias compat


_GROUND_SYSTEM = (
    "You are a UI element grounding model. Given a screenshot, locate the requested element. "
    "Return ONLY valid JSON, no markdown, in exactly this format: "
    '{"x": 0.72, "y": 0.44, "confidence": 0.94} '
    "where x,y are NORMALIZED coordinates 0..1 relative to the image size. "
    "If the element is not visible, return {\"x\": -1, \"y\": -1, \"confidence\": 0.0}."
)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```\w*\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"VLM não retornou JSON: {text[:300]!r}")
    return json.loads(m.group(0))


def _parse_grounding(d: dict) -> GroundingResult:
    # formato MAI-UI/Ollama: {"bbox_2d": [x1,y1,x2,y2]} em escala 0..1000
    if "bbox_2d" in d and isinstance(d["bbox_2d"], (list, tuple)) and len(d["bbox_2d"]) == 4:
        x1, y1, x2, y2 = (float(v) for v in d["bbox_2d"])
        scale = 1000.0 if max(x1, y1, x2, y2) > 1.5 else 1.0
        return GroundingResult(x=round(((x1 + x2) / 2) / scale, 4),
                               y=round(((y1 + y2) / 2) / scale, 4),
                               confidence=float(d.get("confidence", 0.8)))
    x = float(d.get("x", -1))
    y = float(d.get("y", -1))
    if max(x, y) > 1.5:  # veio em 0..1000 → normaliza
        x, y = x / 1000.0, y / 1000.0
    return GroundingResult(x=round(x, 4), y=round(y, 4),
                           confidence=float(d.get("confidence", 0.5)))


class LMStudioVisionModel(VisionModel):
    """Grounding via qualquer endpoint OpenAI-compatible (LM Studio, llama.cpp, Ollama)."""

    def __init__(self, base_url: str = "http://127.0.0.1:1234/v1",
                 model: str = DEFAULT_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def locate(self, screenshot, instruction: str) -> GroundingResult:
        import base64 as _b64
        from PIL import Image as _Image
        import io as _io

        if isinstance(screenshot, _Image.Image):
            buf = _io.BytesIO()
            screenshot.convert("RGB").save(buf, format="JPEG", quality=60)
            b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
        else:
            b64 = str(screenshot)
        return self.locate_sync(b64, instruction)

    def locate_sync(self, screenshot_b64: str, instruction: str) -> GroundingResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _GROUND_SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Locate the {instruction}."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"}},
                ]},
            ],
            "temperature": 0.0,
            "max_tokens": 100,
        }
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{self.base_url}/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_grounding(_extract_json(content))

    def to_click(self, res: GroundingResult, real_size: tuple[int, int]) -> Action:
        rw, rh = real_size
        return Action(type="click", x=int(res.x * rw), y=int(res.y * rh))


# --- legado (compat): VLM como agente de ação; loop atual usa locate() --------
_AGENT_SYSTEM = (
    "Você é um controlador de computador. Recebe instrução + screenshot + elementos UIA. "
    "Responda SOMENTE com um JSON válido, sem markdown, no formato: "
    '{"action":"click|type|scroll|hotkey|done","x":0-1000,"y":0-1000,"text":"...","key":"..."} '
    "x,y são coordenadas NORMALIZADAS 0-1000 relativas à imagem. "
    "Para digitar use type+text. Para Enter use hotkey+key='enter'. "
    "Se a tarefa terminou, retorne action=done."
)


def ground_action(
    instruction: str,
    screenshot_b64: str,
    uia_summary: str = "",
    base_url: str = "http://127.0.0.1:1234/v1",
    model: str = DEFAULT_MODEL,
    vlm_size: tuple[int, int] = (960, 600),
    real_size: tuple[int, int] = (1920, 1080),
) -> Action:
    user_text = f"Instrução: {instruction}\nElementos UIA (podados):\n{uia_summary[:4000] or '(vazio)'}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _AGENT_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"}},
            ]},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
    }
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{base_url.rstrip('/')}/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
    content = data["choices"][0]["message"]["content"]
    d = _extract_json(content)
    act = str(d.get("action", "done")).lower()
    rw, rh = real_size
    if act == "click":
        x1000 = max(0, min(1000, int(d.get("x", 500))))
        y1000 = max(0, min(1000, int(d.get("y", 500))))
        x = int(x1000 / 1000 * rw)
        y = int(y1000 / 1000 * rh)
        return Action(type="click", x=x, y=y)
    if act == "type":
        return Action(type="type", text=str(d.get("text", "")))
    if act == "scroll":
        return Action(type="scroll", text=str(d.get("text", "-800")))
    if act == "hotkey":
        return Action(type="hotkey", key=str(d.get("key", "enter")))
    return Action(type="done")


if __name__ == "__main__":
    import sys

    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:1234/v1"
    print(json.dumps(check_server(base), indent=2))
