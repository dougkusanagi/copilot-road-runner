"""Estado da tarefa F1/F3: memória que dura toda a execução (§4.1, §5.1).

- O modelo atualiza subobjetivos/fatos com referências observadas;
  o Python armazena e valida. Fato != hipótese.
- Resumo nunca apaga falhas ainda relevantes.
- Preferências/procedimentos entre sessões são separados e versionados;
  nunca tratados como observação atual da tela (fora deste módulo).
"""

from __future__ import annotations

from schemas import TaskState

MAX_FAILURES = 5
MAX_EVIDENCES = 50


def init(objective: str) -> TaskState:
    return TaskState(objective=objective, subgoal=objective)


def apply_update(state: TaskState, update: dict) -> TaskState:
    """Aplica atualização compacta do modelo, validada (puro, testável)."""
    if not isinstance(update, dict):
        return state
    sub = update.get("subgoal") or update.get("subobjetivo")
    if isinstance(sub, str) and sub.strip():
        state.subgoal = sub.strip()[:300]
    for key in ("pending", "pendencias"):
        val = update.get(key)
        if isinstance(val, list):
            state.pending = [str(v)[:200] for v in val[:20]]
    for key in ("done_items", "concluidas", "done"):
        val = update.get(key)
        if isinstance(val, list):
            for v in val[:20]:
                s = str(v)[:200]
                if s and s not in state.done_items:
                    state.done_items.append(s)
    facts = update.get("facts") or update.get("fatos")
    if isinstance(facts, dict):
        for k, v in list(facts.items())[:20]:
            state.facts[str(k)[:120]] = str(v)[:300]
    hyps = update.get("hypotheses") or update.get("hipoteses")
    if isinstance(hyps, dict):
        for k, v in list(hyps.items())[:20]:
            state.hypotheses[str(k)[:120]] = str(v)[:300]
    return state


def add_evidence(state: TaskState, evidence: str) -> None:
    e = (evidence or "").strip()[:300]
    if e and e not in state.evidences:
        state.evidences.append(e)
        del state.evidences[:-MAX_EVIDENCES]


def add_failure(state: TaskState, failure: str) -> None:
    f = (failure or "").strip()[:300]
    if f:
        state.recent_failures.append(f)
        del state.recent_failures[:-MAX_FAILURES]


def compact(state: TaskState) -> str:
    """Resumo curto p/ o prompt (nunca apaga falhas relevantes)."""
    parts = [f"objetivo: {state.objective[:150]}"]
    if state.subgoal and state.subgoal != state.objective:
        parts.append(f"subobjetivo: {state.subgoal[:150]}")
    if state.done_items:
        parts.append("concluídas: " + "; ".join(state.done_items[-5:]))
    if state.pending:
        parts.append("pendências: " + "; ".join(state.pending[:5]))
    if state.recent_failures:
        parts.append("falhas recentes: " + "; ".join(state.recent_failures[-3:]))
    if state.evidences:
        parts.append("evidências confirmadas: " + "; ".join(state.evidences[-5:]))
    if state.facts:
        parts.append("fatos: " + "; ".join(f"{k}={v}" for k, v in list(state.facts.items())[-5:]))
    return " | ".join(parts)
