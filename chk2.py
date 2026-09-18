# -*- coding: utf-8 -*-
from PIL import Image
im = Image.open("overlay_glow_proof.png")
px = im.load()
w, h = im.size
print("size:", im.size)
print("top y=2:", [px[x, 2] for x in range(0, w, 600)])
print("top y=8:", [px[x, 8] for x in range(0, w, 600)])
print("top y=20:", [px[x, 20] for x in range(0, w, 600)])
print("left x=4:", [px[4, y] for y in range(0, h, 400)])
print("bottom y=h-4:", [px[x, h - 4] for x in range(0, w, 600)])
print("right x=w-4:", [px[w - 4, y] for y in range(0, h, 400)])
