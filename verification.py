"""Verificação F3: confirmação específica do efeito (§4.3).

- Progresso é específico do efeito: valor digitado, seleção, arquivo salvo
  ou diálogo esperado. Mudança de título/árvore, isoladamente, NÃO confirma.
- Sem 500+300 ms fixos: espera cancelável por condição/evento, com polling
  curto limitado e deadline. Timeout retorna observação, sem inventar sucesso.
- Modelo propõe done com evidências; Python veta evidência ausente/obsoleta.
"""

from __future__ import annotations

import time

import safety


def wait_for_condition(cond, deadline_s: float = 2.0, poll_s: float = 0.1) -> tuple[bool, float]:
    """Espera cancelável até cond() verdadeiro ou deadline/cancelamento.

    Retorna (ok, esperados_ms). Timeout/cancelamento = (False, elapsed).
    """
    t0 = time.perf_counter()
    deadline = max(0.05, deadline_s)
    while True:
        try:
            if cond():
                return True, (time.perf_counter() - t0) * 1000
        except Exception:
            pass
        if safety.stop_requested():
            return False, (time.perf_counter() - t0) * 1000
        if time.perf_counter() - t0 >= deadline:
            return False, (time.perf_counter() - t0) * 1000
        time.sleep(min(poll_s, 0.1))


def confirm_effect(
    action_type: str, expected: str = "", before: str = "", after: str = "", value: str = ""
) -> tuple[bool, str]:
    """Confirmação específica do efeito (puro, testável).

    Retorna (confirmado, nota). Título/árvore mudando sozinho NÃO confirma.
    """
    if action_type == "type" and expected:
        if value and (expected.strip()[:40] in value or "text visible in focused field" in value):
            return True, "efeito confirmado: valor digitado visível"
        return False, "não confirmado: texto esperado ausente no campo focado"
    if action_type in ("open", "focus"):
        if after and before != after:
            return False, f"janela mudou p/ {after!r}; efeito ainda não confirmado"
        return False, "não confirmado: sem mudança observada"
    if action_type == "answer":
        return (bool(expected), "fato reportado" if expected else "não confirmado: answer vazio")
    if action_type == "done":
        return False, "done exige evidências (verificar à parte)"
    if action_type == "hotkey:ctrl+t":
        if "window " in after and " -> " in after:
            return True, "efeito confirmado: nova aba observada"
        return False, "não confirmado: nova aba não observada"
    # Cliques/scroll/hotkey: confirmação exige observação seguinte específica;
    # aqui só registra envio (confirmação vem do próximo snapshot).
    return False, "enviado; confirmação pendente na próxima observação"


def done_evidence_ok(
    proposed: list[str], state_evidences: list[str], hist_labels: list[str] | None = None
) -> tuple[bool, str]:
    """Veta done sem referência exata a evidência confirmada.

    ``hist_labels`` permanece para compatibilidade; histórico de ações nunca
    conta como evidência de conclusão.
    """
    _ = hist_labels
    if not proposed:
        return False, "done vetado: sem evidências"
    desconhecidas = [e for e in proposed if e not in state_evidences]
    if desconhecidas:
        return False, f"done vetado: evidência obsoleta/ausente: {desconhecidas[0][:80]}"
    return True, "evidências conferem"
