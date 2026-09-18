"""Windows UI Automation via pywinauto (backend uia). Rápido e podado."""
from __future__ import annotations

import time

from schemas import UIElement

MAX_DEPTH = 6
MAX_ELEMENTS = 300


def snapshot(timeout: float = 5.0) -> list[UIElement]:
    """Lista elementos visíveis das janelas top-level. Podado p/ ser rápido."""
    from pywinauto import Desktop

    out: list[UIElement] = []
    t0 = time.perf_counter()
    try:
        desk = Desktop(backend="uia")
        windows = desk.windows(top_level_only=True, visible_only=True)
    except Exception:
        return out

    def walk(elem, depth: int) -> None:
        if len(out) >= MAX_ELEMENTS or depth > MAX_DEPTH:
            return
        if time.perf_counter() - t0 > timeout:
            return
        try:
            info = elem.element_info
            name = (getattr(info, "name", "") or "")[:120]
            aid = (getattr(info, "automation_id", "") or "")[:120]
            ctype = (getattr(info, "control_type", "") or "")[:60]
            try:
                r = info.rectangle
                rect = (r.left, r.top, r.right, r.bottom)
            except Exception:
                rect = (0, 0, 0, 0)
            # ignora elementos totalmente vazios/invisíveis minúsculos
            if name or aid:
                out.append(UIElement(name=name, automation_id=aid,
                                     control_type=str(ctype), rect=rect, depth=depth))
            for child in elem.children():
                walk(child, depth + 1)
                if len(out) >= MAX_ELEMENTS:
                    break
        except Exception:
            return

    for w in windows[:20]:  # limita janelas p/ velocidade
        try:
            walk(w, 0)
        except Exception:
            continue
        if len(out) >= MAX_ELEMENTS or time.perf_counter() - t0 > timeout:
            break
    return out


def find_window_titles() -> list[str]:
    from pywinauto import Desktop

    try:
        desk = Desktop(backend="uia")
        return [w.window_text() for w in desk.windows(top_level_only=True, visible_only=True)][:40]
    except Exception:
        return []


if __name__ == "__main__":
    els = snapshot()
    print(f"elements={len(els)}")
    for e in els[:15]:
        print(f"  [{e.control_type}] name={e.name!r} aid={e.automation_id!r} rect={e.rect}")
