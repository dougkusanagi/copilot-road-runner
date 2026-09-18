# -*- coding: utf-8 -*-
from PIL import Image
img = Image.open("overlay_glow_proof.png")
w, h = img.size
px = img.load()
print("size:", img.size)
for y in (0, 2, 6, 12, 20, 40):
    row = [px[x, y] for x in range(0, w, 500)]
    print("y=", y, row[:8])
for x in (2, 6, 12):
    col = [px[x, y] for y in range(0, h, 300)]
    print("x=", x, col[:8])
