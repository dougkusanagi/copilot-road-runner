"""Action scorer ultraleve: regras, sem ML. Retorna melhor elemento + confiança."""
from __future__ import annotations

from schemas import UIElement


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def score(query: str, el: UIElement) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    name = _norm(el.name)
    aid = _norm(el.automation_id)
    if q == aid:
        return 1.0
    if q == name:
        return 0.95
    if q == aid.lower() or q == name.lower():
        return 0.9
    if aid and q in aid:
        return 0.8
    if name and q in name:
        return 0.7
    # match por palavras
    words = [w for w in q.split() if len(w) > 2]
    if words and name and all(w in name for w in words):
        return 0.65
    return 0.0


def pick(query: str, elements: list[UIElement]) -> tuple[UIElement | None, float]:
    best: UIElement | None = None
    best_s = 0.0
    for el in elements:
        s = score(query, el)
        if s > best_s:
            best, best_s = el, s
    return best, best_s


THRESHOLD_VLM = 0.6  # abaixo disso → fallback VLM
