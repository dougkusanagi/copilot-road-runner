p = "planner.py"
s = open(p, encoding="utf-8").read()
old = '            "temperature": self.temperature,\n            "max_tokens": 160,'
new = ('            "temperature": self.temperature,\n'
       '            # reasoning hibrido do MiniCPM5: modo rapido (sem thinking);\n'
       '            # thinking consome tokens/latencia sem ajudar em decisao curta.\n'
       '            "chat_template_kwargs": {"enable_thinking": False},\n'
       '            "max_tokens": 256,')
assert old in s, "padrao nao encontrado"
open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new))
print("ok")
