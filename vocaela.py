"""Visual actor: Vocaela-2-500M-1024R2 (vocaela/Vocaela-2-500M-1024R2).

Enxerga + localiza + produz ação visual. NÃO planeja, NÃO decide tools.

Formato copiado do model card oficial (não inventado):
- System message: `Vocaela_Computer_Use_System_Message` abaixo, verbatim.
- Entrada: screenshot (longest edge 1024 no treino; recomendado < 2048)
  + instrução curta ("Click the ...").
- Saída: <Action>[{...}]</Action>, JSON array; coordenadas [x,y] em 0..1,
  [0,0]=top-left. Ex: {"action": "click", "coordinate": [0.1, 0.5]}.
- Ação desktop: click/mouse_move/drag(+coordinate2)/right_click/
  middle_click/double_click/scroll(scroll_direction)/press_key(key,presses)/
  hotkey(hotkeys)/type(text).

Runtime: GGUF oficial vocaela/Vocaela-2-500M-1024R2-GGUF via llama-server
(suporte a llama.cpp documentado no card + repo demo). O adapter fala
OpenAI-compatible (/chat/completions com image_url); se o runtime exigir
outro protocolo, trocar SÓ este arquivo.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import time
from typing import TYPE_CHECKING, Literal

import httpx
from PIL import Image
from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    from schemas import Action

# --- system message oficial p/ computer use (verbatim do model card) ---------
VOCAELA_COMPUTER_SYSTEM = """You are an assistant trained to navigate the computer screen.
Given a task instruction, a screen observation, and an action history sequence,
output the next actions and wait for the next observation.

## Allowed ACTION_TYPEs and parameters:
1. `PRESS_KEY`: Press one specified key. Two parameters: `key`, string, the single key to press; `presses`, integer, the number of times to press the key (default is 1).
2. `TYPE`: Type a string into an element. Parameter: `text`, string, the text to type.
3. `MOUSE_MOVE`: Move the mouse cursor to a specified position. Parameter: `coordinate`, formatted as [x,y], the position to move the cursor to.
4. `CLICK`: Click left mouse button once on an element. Parameter: `coordinate`, formatted as [x,y], the position to click on.
5. `DRAG`: Drag the cursor with the left mouse button pressed, start and end positions are specified. Two parameters: `coordinate`, formatted as [x,y], the start position to drag from; `coordinate2`, formatted as [x2,y2], the end position to drag to.
6. `RIGHT_CLICK`: Click right mouse button once on an element. Parameter: `coordinate`, formatted as [x,y], the position to right click on.
7. `MIDDLE_CLICK`: Click middle mouse button once on an element. Parameter: `coordinate`, formatted as [x,y], the position to middle click on.
8. `DOUBLE_CLICK`: Click left mouse button twice on an element. Parameter: `coordinate`, formatted as [x,y], the position to double click on.
9. `SCROLL`: Scroll the screen (via mouse wheel). Parameter: `scroll_direction`, the direction (`up`/`down`/`left`/`right`) to scroll.
10. `HOTKEY`: Press a combination of keys simultaneously. Parameter: `hotkeys`, list of strings, the keys to press together.
11. `ANSWER`: Answer a specific question. Required parameter: `text`, string, the answer text.

* NOTE *: The `coordinate` and `coordinate2` parameters (formatted as [x,y]) are the relative coordinates on the screenshot scaled to range of 0-1, [0,0] is the top-left corner and [1,1] is the bottom-right corner.

## Format your response as
<Action>the next actions</Action>

`The next actions` can be one or multiple actions. Format `the next actions` as a JSON array of objects as below, each object is an action:
[{"action": "<ACTION_TYPE>", "key": "<key>", "presses": <presses>, "hotkeys": ["<hotkeys>"], "text": "<text>", "coordinate": [x,y], "coordinate2": [x2,y2], "scroll_direction": "<scroll_direction>"}]

If a parameter is not applicable, don't include it in the JSON object.
"""

VisualActionType = Literal["click", "double_click", "right_click", "middle_click",
                           "move", "drag", "scroll", "type", "key", "hotkey",
                           "answer"]

_VOC_TO_INTERNAL = {
    "CLICK": "click", "DOUBLE_CLICK": "double_click", "RIGHT_CLICK": "right_click",
    "MIDDLE_CLICK": "middle_click", "MOUSE_MOVE": "move", "DRAG": "drag",
    "SCROLL": "scroll", "TYPE": "type", "PRESS_KEY": "key", "HOTKEY": "hotkey",
    "ANSWER": "answer",  # resposta textual: vira observação, não input
}


class VisualAction(BaseModel):
    """Ação visual normalizada. Coordenadas sempre 0.0..1.0 relativas ao crop."""
    type: VisualActionType
    x: float | None = None
    y: float | None = None
    x2: float | None = None
    y2: float | None = None
    text: str | None = None
    key: str | None = None
    presses: int = 1
    scroll_direction: str | None = None
    dropped: int = 0  # ações extras do array que NÃO foram executadas

    @field_validator("x", "y", "x2", "y2")
    @classmethod
    def _range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"coordenada fora de 0..1: {v}")
        return v


def _prep_image(img: Image.Image, max_long_edge: int = 1024,
                jpeg_quality: int = 70) -> tuple[str, tuple[int, int]]:
    """Redimensiona p/ longest-edge<=1024 preservando aspect. Retorna (b64, (w,h))."""
    img = img.convert("RGB")
    w, h = img.size
    long_edge = max(w, h)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)
        w, h = img.size
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    return base64.b64encode(buf.getvalue()).decode("ascii"), (w, h)


def parse_vocaela_output(text: str) -> VisualAction:
    """Parser do formato oficial <Action>[{...}]</Action> (+fallbacks tolerantes).

    Usa a PRIMEIRA ação do array (passo low-level único); `dropped` conta
    as demais p/ log. Aceita tipos em qualquer caixa. Erro honesto se
    inválido — nunca inventa coordenada.
    """
    t = text.strip()
    m = re.search(r"<Action>(.*?)</Action>", t, re.DOTALL | re.IGNORECASE)
    payload = m.group(1).strip() if m else t
    payload = re.sub(r"^```(?:json)?\s*|\s*```$", "", payload).strip()
    try:
        d = json.loads(payload)
    except Exception:
        m2 = re.search(r"\[.*\]|\{.*\}", payload, re.DOTALL)
        if not m2:
            raise ValueError(f"Vocaela não retornou ação válida: {text[:200]!r}")
        d = json.loads(m2.group(0))
    if isinstance(d, list):
        if not d:
            raise ValueError(f"Vocaela devolveu array vazio: {text[:200]!r}")
        first, dropped = d[0], len(d) - 1
    else:
        first, dropped = d, 0
    if not isinstance(first, dict):
        raise ValueError(f"ação Vocaela malformada: {text[:200]!r}")
    va = _normalize(first)
    va.dropped = dropped
    return va


def _coord(v: object, what: str) -> tuple[float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"{what} precisa ser [x,y] 0..1, veio {v!r}")
    x, y = float(v[0]), float(v[1])
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(f"{what} fora de 0..1: {[x, y]}")
    return round(x, 4), round(y, 4)


def _normalize(d: dict) -> VisualAction:
    raw_type = str(d.get("action", "")).strip().upper()
    if not raw_type or raw_type not in _VOC_TO_INTERNAL:
        raise ValueError(f"action desconhecida do Vocaela: {raw_type!r} em {d}")
    t = _VOC_TO_INTERNAL[raw_type]
    kw: dict = {"type": t}
    if "coordinate" in d and d["coordinate"] is not None:
        kw["x"], kw["y"] = _coord(d["coordinate"], "coordinate")
    if "coordinate2" in d and d["coordinate2"] is not None:
        kw["x2"], kw["y2"] = _coord(d["coordinate2"], "coordinate2")
    if t == "drag" and ("x" not in kw or "x2" not in kw):
        raise ValueError(f"drag precisa de coordinate+coordinate2: {d}")
    if t in ("click", "double_click", "right_click", "middle_click", "move") \
            and "x" not in kw:
        raise ValueError(f"{t} precisa de coordinate: {d}")
    if t in ("type", "answer"):
        kw["text"] = str(d.get("text", ""))
        if not kw["text"]:
            raise ValueError(f"{t} sem text: {d}")
    if t == "key":
        kw["key"] = str(d.get("key", ""))
        if not kw["key"]:
            raise ValueError(f"press_key sem key: {d}")
        presses = d.get("presses", 1)
        kw["presses"] = presses if isinstance(presses, int) and presses > 0 else 1
    if t == "hotkey":
        hk = d.get("hotkeys", [])
        if not isinstance(hk, list) or not hk:
            raise ValueError(f"hotkey sem hotkeys: {d}")
        kw["key"] = "+".join(str(k) for k in hk)
    if t == "scroll":
        sd = str(d.get("scroll_direction", "down")).lower()
        if sd not in ("up", "down", "left", "right"):
            sd = "down"
        kw["scroll_direction"] = sd
        kw["text"] = "-800" if sd in ("down", "right") else "800"
    return VisualAction(**kw)


def visual_to_action(va: VisualAction, size: tuple[int, int],
                     origin: tuple[int, int] = (0, 0)) -> Action:
    """Converte 0..1 (relativo ao crop) → pixels físicos. Import tardio p/ testes."""
    from schemas import Action

    w, h = size
    ox, oy = origin

    def px(f: float | None, total: int, off: int) -> int | None:
        return None if f is None else off + int(round(f * total))

    t = va.type
    if t in ("click", "double_click", "right_click", "middle_click", "move"):
        return Action(type=t, x=px(va.x, w, ox), y=px(va.y, h, oy))
    if t == "drag":
        return Action(type="drag", x=px(va.x, w, ox), y=px(va.y, h, oy),
                      x2=px(va.x2, w, ox), y2=px(va.y2, h, oy))
    if t == "scroll":
        # key carrega a direção: left/right -> hscroll no executor
        return Action(type="scroll", text=va.text or "-800",
                      key=va.scroll_direction or "down")
    if t == "type":
        return Action(type="type", text=va.text)
    if t in ("key", "hotkey"):
        return Action(type="hotkey", key=va.key, presses=va.presses)
    if t == "answer":
        return Action(type="answer", text=va.text)
    raise ValueError(f"ação visual sem mapeamento: {t}")


class VocaelaAdapter:
    """Adapter específico do Vocaela. screenshot+instrução → VisualAction."""

    def __init__(self, base_url: str = "http://127.0.0.1:8082/v1",
                 model: str = "Vocaela-2-500M-1024R2",
                 timeout_s: float = 180.0, max_long_edge: int = 1024):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_long_edge = max_long_edge

    def check(self) -> dict:
        try:
            r = httpx.get(f"{self.base_url}/models", timeout=10.0)
            r.raise_for_status()
            data = r.json()
            return {"ok": True,
                    "models": [m.get("id", "?") for m in data.get("data", [])]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def act(self, screenshot: Image.Image | str,
                  instruction: str,
                  history: list[str] | None = None) -> tuple[VisualAction, float]:
        return await asyncio.to_thread(self.act_sync, screenshot, instruction, history)

    def act_sync(self, screenshot: Image.Image | str,
                 instruction: str,
                 history: list[str] | None = None) -> tuple[VisualAction, float]:
        """Retorna (VisualAction, vision_ms).

        `history`: últimas ações visuais como texto (o system oficial fala em
        "action history sequence", que o adapter não enviava — §5.5).
        """
        if isinstance(screenshot, Image.Image):
            b64, _ = _prep_image(screenshot, self.max_long_edge)
        else:
            b64 = str(screenshot)
        user_text = instruction
        if history:
            seq = "\n".join(f"- {h[:120]}" for h in history[-3:])
            user_text = (f"Action history sequence:\n{seq}\n"
                         f"Current instruction: {instruction}")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": VOCAELA_COMPUTER_SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]},
            ],
            "temperature": 0.0,
            "max_tokens": 128,
        }
        t0 = time.perf_counter()
        data: dict | None = None
        last_err: Exception | None = None
        for attempt in range(3):  # §5.6: retry curto p/ slot ocupado/timeout
            try:
                with httpx.Client(timeout=self.timeout_s) as c:
                    r = c.post(f"{self.base_url}/chat/completions", json=payload)
                    r.raise_for_status()
                    data = r.json()
                break
            except Exception as e:
                last_err = e
                retryable = isinstance(e, httpx.TimeoutException) or (
                    isinstance(e, httpx.HTTPStatusError)
                    and e.response is not None and e.response.status_code >= 500)
                if not retryable or attempt == 2:
                    break
                time.sleep(0.5 * (attempt + 1))
        if data is None:
            raise RuntimeError(f"vocaela HTTP falhou: {last_err}")
        ms = (time.perf_counter() - t0) * 1000
        content = data["choices"][0]["message"]["content"]
        return parse_vocaela_output(content), ms
