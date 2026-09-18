# -*- coding: utf-8 -*-
import ctypes
from ctypes import wintypes
u = ctypes.windll.user32
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetWindowPos.restype = wintypes.BOOL
import tkinter as tk
r = tk.Tk()
r.overrideredirect(True)
r.geometry("1080x1920+1920+0")
r.update_idletasks(); r.update()
hwnd = u.GetParent(r.winfo_id()) or r.winfo_id()
print("ret:", u.SetWindowPos(hwnd, -1, 1920, -708, 1080, 1920, 0x0010 | 0x0040))
rc = wintypes.RECT()
u.GetWindowRect(hwnd, ctypes.byref(rc))
print("rect:", rc.left, rc.top, rc.right, rc.bottom)
last_err = ctypes.get_last_error()
print("err:", last_err)
