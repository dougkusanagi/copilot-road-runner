# -*- coding: utf-8 -*-
import subprocess, sys, time
import mss
from PIL import Image

p = subprocess.Popen([sys.executable, "overlay.py"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)
with mss.mss() as sct:
    s1 = sct.grab(sct.monitors[0])
    img1 = Image.frombytes("RGB", s1.size, s1.rgb)
time.sleep(0.9)
with mss.mss() as sct:
    s2 = sct.grab(sct.monitors[0])
    img2 = Image.frombytes("RGB", s2.size, s2.rgb)
p.terminate()

w, h = img1.size
def sample(img):
    px = img.load()
    row = [px[x, y] for y in (1, 5, 10) for x in range(0, w, 97)]
    col = [px[x, y] for x in (1, 5, 10) for y in range(0, h, 97)]
    blue = lambda c: c[2] > 100 and c[2] > c[0] + 30
    return sum(map(blue, row)) / len(row), sum(map(blue, col)) / len(col)

r1, r2 = sample(img1), sample(img2)
print(f"topo azul {r1[0]:.0%} | esq azul {r1[1]:.0%}")
print(f"topo azul {r2[0]:.0%} | esq azul {r2[1]:.0%}")
print("pulso variou:", abs(sum(r1) - sum(r2)) > 1e-6)
img1.save("overlay_glow_proof.png")
img2.save("overlay_glow_proof2.png")
ok = r1[0] > 0.5 and r1[1] > 0.5 and r2[0] > 0.5
print("GLOW OK" if ok else "GLOW FALHOU")
