# -*- coding: utf-8 -*-
import json
import config as cfgmod
from loop import run
cfg = cfgmod.load("config.json")
summary = run("Abra o Notepad e escreva: Ola, este texto foi escrito por um agente local.", cfg)
print("SUMMARY:" + json.dumps(summary, ensure_ascii=False))
