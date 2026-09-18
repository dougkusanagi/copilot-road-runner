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


def active_window_snapshot(timeout: float = 5.0,
                           max_elements: int = 120) -> tuple[list[dict], str]:
    """Elementos úteis da janela ATIVA, formato compacto p/ decisão rápida.

    Retorna (items, title) onde items = [{id, name, type, bounds}].
    Ignora invisíveis, sem nome, com área trivial ou fora da janela.
    """
    from pywinauto import Desktop

    t0 = time.perf_counter()
    items: list[dict] = []
    try:
        desk = Desktop(backend="uia")
        active = None
        # 1. tenta handle da janela em foreground (mais preciso)
        try:
            from pywinauto.win32functions import GetForegroundWindow

            h = GetForegroundWindow()
            if h:
                try:
                    active = desk.window(handle=h).wrapper_object()
                except Exception:
                    active = None
        except Exception:
            pass
        # 2. fallback: enumera e pega a que tem foco
        if active is None:
            try:
                wins = desk.windows(top_level_only=True, visible_only=True)
            except Exception:
                return [], ""
            for w in wins:
                try:
                    for attr in ("has_focus", "is_active", "has_keyboard_focus"):
                        fn = getattr(w, attr, None)
                        if callable(fn) and fn():
                            active = w
                            break
                    if active is not None:
                        break
                except Exception:
                    continue
            # 3. fallback final: primeira com título
            if active is None:
                for w in wins:
                    try:
                        if (w.window_text() or "").strip():
                            active = w
                            break
                    except Exception:
                        continue
        if active is None:
            return [], ""
        try:
            title = active.window_text() or ""
        except Exception:
            title = ""
        try:
            wr = active.rectangle()
            wrect = (wr.left, wr.top, wr.right, wr.bottom)
        except Exception:
            wrect = None

        def walk(elem, depth: int) -> None:
            if len(items) >= max_elements or depth > MAX_DEPTH:
                return
            if time.perf_counter() - t0 > timeout:
                return
            try:
                info = elem.element_info
                name = (getattr(info, "name", "") or "").strip()[:120]
                if not name:
                    pass  # ainda desce p/ filhos
                ctype = str(getattr(info, "control_type", "") or "")[:60]
                try:
                    r = info.rectangle
                    bounds = (r.left, r.top, r.right, r.bottom)
                except Exception:
                    bounds = (0, 0, 0, 0)
                l, t, rr, b = bounds
                area_ok = (rr - l) > 4 and (b - t) > 4
                inside = True
                if wrect is not None:
                    wl, wt, wrr, wb = wrect
                    inside = not (rr < wl or l > wrr or b < wt or t > wb)
                if name and area_ok and inside:
                    items.append({"id": len(items), "name": name,
                                  "type": ctype, "bounds": list(bounds)})
                for child in elem.children():
                    walk(child, depth + 1)
                    if len(items) >= max_elements:
                        break
            except Exception:
                return

        walk(active, 0)
        return items, title
    except Exception:
        return [], ""


if __name__ == "__main__":
    els = snapshot()
    print(f"elements={len(els)}")
    for e in els[:15]:
        print(f"  [{e.control_type}] name={e.name!r} aid={e.automation_id!r} rect={e.rect}")
