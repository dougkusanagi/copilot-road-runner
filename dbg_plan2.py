from planner import MiniCPMPlanner
p = MiniCPMPlanner()
for goal, win in [
    ("Abra o Notepad e escreva: Ola, este texto foi escrito por um agente local.", "Desktop"),
    ("Abra a calculadora e clique no numero 7.", "Desktop"),
]:
    d, ms = p.next_action(goal=goal, window=win, ui_names=[], history=[], last_error="")
    print(round(ms), "ms ->", d.model_dump())
