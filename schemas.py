"""Schemas mínimos do MVP (pydantic)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ActionType = Literal["click", "double_click", "right_click", "middle_click", "move",
                     "drag", "type", "scroll", "hotkey", "open", "focus", "wait",
                     "answer", "done"]
SourceType = Literal["planner", "uia", "vocaela"]


class Action(BaseModel):
    type: ActionType
    x: int | None = None
    y: int | None = None
    x2: int | None = None  # p/ drag: destino
    y2: int | None = None
    text: str | None = None
    key: str | None = None  # p/ hotkey: "enter", "ctrl+l"; p/ scroll: direção
    target: str | None = None  # p/ open: comando/app; p/ focus: substring do título
    ms: int = 0  # p/ wait
    clicks: int = 1
    presses: int = 1  # p/ hotkey: repetições (PRESS_KEY presses do Vocaela)


class Decision(BaseModel):
    action: Action
    source: SourceType
    confidence: float = 0.0
    reason: str = ""
