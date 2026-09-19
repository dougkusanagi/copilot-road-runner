"""Windows UI Automation via pywinauto (backend uia). Rápido e podado."""
from __future__ import annotations

import time

from overlay import is_overlay_title

MAX_DEPTH = 6


def focused_value(max_len: int = 80) -> str:
    """Valor/texto do elemento com foco de teclado (Edit/Document), best-effort.

    Serve p/ o planner saber se `type_text` chegou onde devia. "" se não der.
    """
    try:
        from pywinauto.controls.uiawrapper import UIAWrapper
        from pywinauto.uia_defines import IUIA
        from pywinauto.uia_element_info import UIAElementInfo

        el = IUIA().iuia.GetFocusedElement()
        w = UIAWrapper(UIAElementInfo(el))
        val = ""
        try:
            val = w.iface_value.CurrentValue or ""
        except Exception:
            try:
                val = w.legacy_properties().get("Value") or ""
            except Exception:
                val = ""
        if not val:
            try:
                val = w.window_text() or ""
            except Exception:
                val = ""
        val = " ".join(str(val).split())
        return val[:max_len] + ("…" if len(val) > max_len else "")
    except Exception:
        return ""


def active_window_snapshot(timeout: float = 5.0,
                           max_elements: int = 120) -> tuple[list[dict], str, tuple | None]:
    """Elementos úteis da janela ATIVA, formato compacto p/ decisão rápida.

    Retorna (items, title, wrect) onde items = [{id, name, type, bounds}].
    Ignora invisíveis, sem nome, com área trivial ou fora da janela/tela.
    """
    from pywinauto import Desktop

    t0 = time.perf_counter()
    items: list[dict] = []
    try:
        desk = Desktop(backend="uia")
        active = None
        # 1. tenta handle da janela em foreground (mais preciso)
        try:
            import ctypes

            h = ctypes.windll.user32.GetForegroundWindow()
            if h:
                try:
                    active = desk.window(handle=h).wrapper_object()
                    try:
                        # O overlay (borda "controlado") pode estar em
                        # foreground: nunca é a janela do app (era 'tk' e o
                        # planner tentava focus("tk") no próprio overlay).
                        if is_overlay_title(active.window_text() or ""):
                            active = None
                    except Exception:
                        pass
                except Exception:
                    active = None
        except Exception:
            pass
        # 2. fallback: enumera e pega a que tem foco
        if active is None:
            try:
                wins = desk.windows(top_level_only=True, visible_only=True)
            except Exception:
                return [], "", None
            for w in wins:
                try:
                    if is_overlay_title(w.window_text() or ""):
                        continue
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
                        if is_overlay_title(w.window_text() or ""):
                            continue
                        if (w.window_text() or "").strip():
                            active = w
                            break
                    except Exception:
                        continue
        if active is None:
            return [], "", None
        try:
            title = active.window_text() or ""
        except Exception:
            title = ""
        try:
            wr = active.rectangle()
            wrect = (wr.left, wr.top, wr.right, wr.bottom)
        except Exception:
            wrect = None
        try:  # tela virtual (multi-monitor): candidatos fora dela são lixo
            import ctypes as _ct

            _u = _ct.windll.user32
            vx, vy, vw, vh = (_u.GetSystemMetrics(76), _u.GetSystemMetrics(77),
                              _u.GetSystemMetrics(78), _u.GetSystemMetrics(79))
        except Exception:
            vx, vy, vw, vh = (0, 0, 10000, 10000)

        def walk(elem, depth: int) -> None:
            if len(items) >= max_elements or depth > MAX_DEPTH:
                return
            if time.perf_counter() - t0 > timeout:
                return
            try:
                info = elem.element_info
                name = (getattr(info, "name", "") or "").strip()[:120]
                ctype = str(getattr(info, "control_type", "") or "")[:60]
                try:
                    r = info.rectangle
                    bounds = (r.left, r.top, r.right, r.bottom)
                except Exception:
                    bounds = (0, 0, 0, 0)
                bl, bt, br, bb = bounds
                area_ok = (br - bl) > 4 and (bb - bt) > 4
                cx, cy = (bl + br) // 2, (bt + bb) // 2
                on_screen = vx <= cx < vx + vw and vy <= cy < vy + vh
                inside = True
                if wrect is not None:
                    wl, wt, wrr, wb = wrect
                    inside = not (br < wl or bl > wrr or bb < wt or bt > wb)
                if name and area_ok and inside and on_screen:
                    items.append({"id": len(items), "name": name,
                                  "type": ctype, "bounds": list(bounds)})
                for child in elem.children():
                    walk(child, depth + 1)
                    if len(items) >= max_elements:
                        break
            except Exception:
                return

        walk(active, 0)
        return items, title, wrect
    except Exception:
        return [], "", None
