# -*- coding: utf-8 -*-
import mss
with mss.MSS() as sct:
    for i, m in enumerate(sct.monitors):
        print(i, m["left"], m["top"], m["width"], m["height"])
