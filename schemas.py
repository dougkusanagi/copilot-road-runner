"""Schemas mínimos do MVP (pydantic)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ActionType = Literal["click", "type", "scroll", "hotkey", "open", "done"]
SourceType = Literal["deterministic", "uia", "vlm"]


class UIElement(BaseModel):
    name: str = ""
    automation_id: str = ""
    control_type: str = ""
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    depth: int = 0

    @property
    def center(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)


class Action(BaseModel):
    type: ActionType
    x: int | None = None
    y: int | None = None
    text: str | None = None
    key: str | None = None  # p/ hotkey: "enter", "ctrl+l", ...
    target: str | None = None  # p/ open: comando/app
    clicks: int = 1


class Observation(BaseModel):
    step: int
    screenshot_path: str
    screen_size: tuple[int, int] = (0, 0)
    uia_elements: list[UIElement] = Field(default_factory=list)


class Decision(BaseModel):
    action: Action
    source: SourceType
    confidence: float = 0.0
    reason: str = ""
