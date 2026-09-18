"""Fallback VLM via LM Studio local (endpoint OpenAI-compatible).

Espera um modelo *vision* carregado no LM Studio
(ex: qwen2-vl, llava-1.6, internvl2).
Testa com: GET {base_url}/models
"""
from __future__ import annotations

import json
import re

import httpx

from schemas import Action

DEFAULT_MODEL = "local-vision"  # LM Studio ignora na prática; usa o carregado
TIMEOUT = 120.0


def check_lmstudio(base_url: str = "http://localhost:1234/v1") -> dict:
    """Retorna {'ok': True, 'models': [...]} ou {'ok': False, 'error': ...}."""
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/models", timeout=10.0)
        r.raise_for_status()
        data = r.json()
        models = [m.get("id", "?") for m in data.get("data", [])]
        return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_SYSTEM = (
    "Você é um controlador de computador. Recebe instrução + screenshot + elementos UIA. "
    "Responda SOMENTE com um JSON válido, sem markdown, no formato: "
    '{"action":"click|type|scroll|hotkey|done","x":0-1000,"y":0-1000,"text":"...","key":"..."} '
    "x,y são coordenadas NORMALIZADAS 0-1000 relativas à imagem. "
    "Para digitar use type+text. Para Enter use hotkey+key='enter'. "
    "Se a tarefa terminou, retorne action=done."
)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # remove fences ```json ... ```
    text = re.sub(r"^```\w*\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"VLM não retornou JSON: {text[:300]!r}")
    return json.loads(m.group(0))


def ground_action(
    instruction: str,
    screenshot_b64: str,
    uia_summary: str = "",
    base_url: str = "http://localhost:1234/v1",
    model: str = DEFAULT_MODEL,
    vlm_size: tuple[int, int] = (960, 600),
    real_size: tuple[int, int] = (1920, 1080),
) -> Action:
    """Chama LM Studio e converte coords 0-1000 → pixels reais."""
    user_text = f"Instrução: {instruction}\nElementos UIA (podados):\n{uia_summary[:4000] or '(vazio)'}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
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

    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:1234/v1"
    print(json.dumps(check_lmstudio(base), indent=2))
