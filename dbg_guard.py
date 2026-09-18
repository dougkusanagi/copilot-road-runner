import re
p = "loop.py"
s = open(p, encoding="utf-8").read()

# 1) guardas generalizados
anchor = "def _planner_to_action("
guard = '''NOTEPAD_WORDS = ["notepad", "bloco de notas"]


def _wrong_window(instruction: str, title: str) -> bool:
    """Janela ativa nao tem relacao com o alvo da instrucao? (gate de seguranca)"""
    t = (title or "").lower()
    if _has_any(instruction, CALC_WORDS):
        return "calcul" not in t
    if _has_any(instruction, NOTEPAD_WORDS):
        return "notepad" not in t and "bloco" not in t
    return False


'''
s = s.replace(anchor, guard + anchor, 1)

# 2) veto done prematuro dentro de _planner_to_decision
old_done = '''    if a == "done":
        return Decision(action=Action(type="done"), source="planner", confidence=0.9,
                        reason="planner: done")'''
new_done = '''    if a == "done":
        # gate de seguranca: done sem acao executada = alucinacao do modelo
        hist = ctx.get("hist_labels", [])
        if not hist:
            raise RuntimeError(
                "done sem nenhuma acao executada; continue a tarefa.")
        if re.search(r"escreva|digite|write|type", instruction, re.I) and \\
                not any("type(" in h for h in hist):
            raise RuntimeError(
                "o objetivo pede digitar texto, mas nao ha type_text em recent "
                "actions; nao conclua ainda.")
        return Decision(action=Action(type="done"), source="planner", confidence=0.9,
                        reason="planner: done")'''
assert old_done in s, "done anchor"
s = s.replace(old_done, new_done, 1)
open(p, "w", encoding="utf-8", newline="").write(s)
print("guard ok")
