"""Testes dos adapters (sem rede). Rode: uv run python tests_adapters.py"""
from __future__ import annotations

import planner
import vocaela
from vocaela import visual_to_action


def test_planner_parser() -> None:
    d = planner.extract_json('```json\n{"type":"open_app","app":"notepad"}\n```')
    assert d["type"] == "open_app", d
    d = planner.extract_json('bla bla {"type":"done"} bla')
    assert d["type"] == "done"
    dec = planner.PlannerDecision.model_validate(
        {"type": "visual_action", "instruction": "Click the blue Continue button"})
    dec.assert_no_coords({"type": "visual_action", "instruction": "x"})
    try:
        planner.PlannerDecision.model_validate({"type": "click", "x": 1})
        raise AssertionError("tipo inválido aceito")
    except Exception:
        pass
    try:
        dec.assert_no_coords({"type": "visual_action", "x": 0.5})
        raise AssertionError("coords aceitas")
    except ValueError:
        pass
    p = planner.build_prompt("abrir edge", "Microsoft Edge",
                             ["Address bar", "New tab"], ["Opened Edge"],
                             last_error="focus miss")
    assert "Goal:" in p and "Microsoft Edge" in p and "Last error" in p
    print("planner parser OK")


def test_vocaela_parser() -> None:
    va = vocaela.parse_vocaela_output(
        '<Action>[{"action":"CLICK","coordinate":[0.49,0.06]}]</Action>')
    assert va.type == "click" and abs(va.x - 0.49) < 1e-6 and abs(va.y - 0.06) < 1e-6, va

    va = vocaela.parse_vocaela_output(
        'noise <Action>[{"action":"hotkey","hotkeys":["ctrl","l"]}]</Action> tail')
    assert va.type == "hotkey" and va.key == "ctrl+l", va

    va = vocaela.parse_vocaela_output(
        '<Action>[{"action":"type","text":"ola"},'
        '{"action":"click","coordinate":[0.5,0.5]}]</Action>')
    assert va.type == "type" and va.text == "ola"  # primeira ação do array

    va = vocaela.parse_vocaela_output(
        '<Action>[{"action":"SCROLL","scroll_direction":"up"}]</Action>')
    assert va.type == "scroll" and va.text == "800", va

    va = vocaela.parse_vocaela_output(
        '<Action>[{"action":"double_click","coordinate":[0.1,0.2]}]</Action>')
    assert va.type == "double_click"

    va = vocaela.parse_vocaela_output(
        '<Action>[{"action":"PRESS_KEY","key":"enter"}]</Action>')
    assert va.type == "key" and va.key == "enter"

    va = vocaela.parse_vocaela_output(
        '<Action>[{"action":"DRAG","coordinate":[0.1,0.2],"coordinate2":[0.3,0.4]}]</Action>')
    assert va.type == "drag" and va.x2 == 0.3 and va.y2 == 0.4

    # drag sem coordinate2 → erro honesto
    try:
        vocaela.parse_vocaela_output('<Action>[{"action":"drag","coordinate":[0.1,0.2]}]</Action>')
        raise AssertionError("drag sem coordinate2 aceito")
    except ValueError:
        pass
    print("vocaela parser OK")


def test_visual_to_action() -> None:
    va = vocaela.VisualAction(type="click", x=0.5, y=0.25)
    a = visual_to_action(va, (1920, 1080), (100, 50))
    assert (a.x, a.y) == (100 + 960, 50 + 270), (a.x, a.y)
    print("visual_to_action OK")


if __name__ == "__main__":
    test_planner_parser()
    test_vocaela_parser()
    test_visual_to_action()
    print("TODOS OS TESTES OK")