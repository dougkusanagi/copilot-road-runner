# -*- coding: utf-8 -*-
import ctypes, subprocess, sys, time
from ctypes import wintypes
u = ctypes.windll.user32
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetWindowRect.restype = wintypes.BOOL
u.GetParent.argtypes = [wintypes.HWND]
u.GetParent.restype = wintypes.HWND
p = subprocess.Popen([sys.executable, "overlay.py"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.0)
found = []
@ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
def cb(hwnd, lp):
    name = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(hwnd, name, 64)
    if name.value.startswith("Tk"):
        r = wintypes.RECT()
        ok = u.GetWindowRect(hwnd, ctypes.byref(r))
        found.append((ok, name.value, r.left, r.top, r.right, r.bottom))
    return True
u.EnumWindows(cb, 0)
for f in found:
    print(f)
print("alive:", p.poll() is None)
p.terminate()
