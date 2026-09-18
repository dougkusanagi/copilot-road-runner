"""Action scorer estilo Jev-like (interface + versão simples por heurística).

Ideia: em vez de gerar linguagem, escolhe entre poucas ações candidatas.
Se confidence >= threshold (default 0.80, config.json) → executa.
Senão → vision fallback. Interface pronta p/ um JevScorer futuro.
"""
from __future__ import annotations

import difflib
import re
from typing import Literal

from pydantic import BaseModel

from schemas import UIElement

SCORER_THRESHOLD = 0.80  # configurável via config.json (scorer_threshold)
THRESHOLD_VLM = SCORER_THRESHOLD  # alias compat; abaixo disso → VLM


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# --- legadas (compat): score query × elemento, pick melhor -------------------
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


# --- interface Jev-like -------------------------------------------------------
class CandidateAction(BaseModel):
    kind: Literal["click", "scroll", "vision", "wait"]
    label: str  # ex: 'click("Save")', "scroll_down", "vision_fallback"
    element_id: int | None = None  # id no snapshot compacto (uia.active_window_snapshot)
    name: str = ""  # nome do elemento (p/ click)
    bounds: list[int] | None = None


class ScoredAction(BaseModel):
    candidate: CandidateAction
    confidence: float


class ActionScorer:
    def score(self, goal: str, state: str,
              candidates: list[CandidateAction]) -> list[ScoredAction]:
        raise NotImplementedError


# normalização número-por-extenso → dígito (EN + PT) p/ casar "7" × "Seven"/"Sete"
_NUM_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "zero": "0", "dois": "2", "tres": "3", "três": "3", "quatro": "4",
    "cinco": "5", "seis": "6", "sete": "7", "oito": "8", "nove": "9",
}


def _tokens(s: str) -> list[str]:
    toks = re.findall(r"\w+", _norm(s))
    out = []
    for t in toks:
        out.append(_NUM_WORDS.get(t, t))
    # garante que dígitos soltos ("7") sobrevivam mesmo curtos
    out += re.findall(r"\d+", s)
    return out


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.8
    return difflib.SequenceMatcher(None, a, b).ratio() * 0.7


class SimpleScorer(ActionScorer):
    """Heurística + similaridade de strings. Sem treino, sem modelo."""

    def score(self, goal: str, state: str,
              candidates: list[CandidateAction]) -> list[ScoredAction]:
        gtoks = _tokens(goal)
        scored: list[ScoredAction] = []
        for c in candidates:
            if c.kind == "click":
                ltoks = _tokens(c.name)
                best = 0.0
                for g in gtoks:
                    if len(g) < 3 and not g.isdigit():
                        continue  # tokens curtos ("o","e","de") casam com tudo
                    for lstr in ({c.name.lower()} | set(ltoks)):
                        best = max(best, _similarity(g, lstr))
                # bônus: todos os tokens significativos do goal aparecem no label
                sig = [g for g in gtoks if len(g) > 2]
                if sig and all(any(g in l for l in ltoks) for g in sig):
                    best = max(best, 0.9)
                conf = round(min(1.0, best), 3)
            elif c.kind == "scroll":
                conf = 0.05 if any(w in _norm(goal) for w in ("scroll", "role", "abaixo")) else 0.02
            elif c.kind == "wait":
                conf = 0.01
            else:  # vision_fallback: resíduo (alto só se nada casou bem)
                conf = 0.03
            scored.append(ScoredAction(candidate=c, confidence=conf))
        scored.sort(key=lambda s: s.confidence, reverse=True)
        # vision herda o resíduo: 1 - melhor - margem
        top = scored[0].confidence if scored else 0.0
        for s in scored:
            if s.candidate.kind == "vision":
                s.confidence = round(max(0.03, 1.0 - top - 0.06), 3)
        scored.sort(key=lambda s: s.confidence, reverse=True)
        return scored


class JevScorer(ActionScorer):
    """Placeholder p/ scorer futuro com logits/batch (open-Jev). Não bloqueia o MVP."""

    def score(self, goal: str, state: str,
              candidates: list[CandidateAction]) -> list[ScoredAction]:
        raise NotImplementedError("JevScorer ainda não integrado; usando SimpleScorer.")


JUNK_NAMES = {
    "non client input sink window",
}

# chrome da janela (minimizar/maximizar/fechar): nunca são alvo de clique
CHROME_PREFIXES = ("minimizar ", "maximizar ", "restaurar ", "fechar ",
                   "minimize ", "maximize ", "restore ", "close ")
CHROME_BARE = {"minimizar", "maximizar", "restaurar", "fechar",
               "minimize", "maximize", "restore", "close"}


def build_candidates(items: list[dict], state_title: str = "",
                     max_clicks: int = 12) -> list[CandidateAction]:
    """Candidatos a partir do snapshot compacto [{id,name,type,bounds}].

    Botões/controles clicáveis entram primeiro; elementos Text (ex: display da
    calculadora, que contém dígitos do goal e engana o scorer) só entram se
    sobrar espaço.
    """
    def _accept(it: dict) -> CandidateAction | None:
        name = (it.get("name") or "").strip()
        if not name or len(name) > 60:  # títulos longos (ex: aba de terminal) viram ruído
            return None
        nl = name.lower()
        if nl in seen or nl in JUNK_NAMES or nl in CHROME_BARE:
            return None
        if nl.startswith(CHROME_PREFIXES):
            return None
        if (it.get("type") or "").lower() in skip_types:
            return None
        if state_title and nl == state_title.lower():
            return None  # a própria janela nunca é alvo de clique
        seen.add(nl)
        return CandidateAction(kind="click", label=f'click("{name}")',
                               element_id=it.get("id"), name=name,
                               bounds=it.get("bounds"))

    cands: list[CandidateAction] = []
    seen: set[str] = set()
    skip_types = {"window", "titlebar", "menubar"}
    leftovers: list[CandidateAction] = []
    for it in items:
        c = _accept(it)
        if c is None:
            continue
        if (it.get("type") or "").lower() == "text":
            leftovers.append(c)  # texto estático: só se sobrar vaga
        else:
            cands.append(c)
        if len(cands) >= max_clicks:
            break
    if len(cands) < max_clicks:
        for c in leftovers:
            if len(cands) >= max_clicks:
                break
            cands.append(c)
    cands.append(CandidateAction(kind="scroll", label="scroll_down"))
    cands.append(CandidateAction(kind="vision", label="vision_fallback"))
    cands.append(CandidateAction(kind="wait", label="wait"))
    return cands
