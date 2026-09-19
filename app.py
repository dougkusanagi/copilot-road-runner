"""Tray + janela Spotlight (main.py --ui). Extra `ui`: uv sync --extra ui.

Threads:
  principal   webview.start() (bloqueante, exigência do pywebview)
  tray        pystray.Icon.run() em daemon thread
  agente      loop.run() em thread própria; a janela se ESCONDE antes de
              agir (nunca aparece nos screenshots nem rouba foco) e volta no fim
  ditado      stt.MicSource (callback do PortAudio só enfileira)

Python -> JS: window.evaluate_js("window.crr.<fn>(...)") — thread-safe.
JS -> Python: window.pywebview.api.<método> (classe JsApi).
"""
from __future__ import annotations

import io
import json
import sys
import threading
import time
from pathlib import Path

UI_HTML = Path(__file__).resolve().parent / "ui" / "index.html"


def js_call(fn: str, *args) -> str:
    """Gera a chamada JS p/ window.crr.<fn>(args JSON). Puro, testável."""
    return f"window.crr.{fn}({', '.join(json.dumps(a, ensure_ascii=False) for a in args)})"


class LineTee(io.TextIOBase):
    """stdout do agente: ecoa no console real e manda cada linha p/ a UI."""

    def __init__(self, real, on_line):
        self.real = real
        self.on_line = on_line
        self._buf = ""

    def write(self, s: str) -> int:
        self.real.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.on_line(line.rstrip())
        return len(s)

    def flush(self) -> None:
        self.real.flush()

    @property
    def encoding(self):  # print() consulta
        return getattr(self.real, "encoding", "utf-8")


def classify(line: str) -> str:
    """Classe CSS p/ a linha de log (só cosmética)."""
    low = line.lower()
    if "parado" in low or "offline" in low or "falhou" in low or "erro" in low:
        return "err"
    if low.startswith("done") or "] verify" in low:
        return "ok"
    return ""


class JsApi:
    """Métodos chamáveis do JS (window.pywebview.api.*)."""

    def __init__(self, app: App):
        self._app = app

    def ready(self) -> None:
        self._app.js("hotkey", self._app.hotkey)

    def submit(self, text: str) -> None:
        self._app.run_task(str(text or "").strip())

    def dictation_start(self) -> None:
        self._app.dictation_start()

    def dictation_stop(self, send: bool = False) -> None:
        self._app.dictation_stop(bool(send))

    def abort(self) -> None:
        import safety

        safety.stop()

    def hide(self) -> None:
        self._app.hide()


class App:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        ui = cfg.get("ui", {})
        self.hotkey = str(ui.get("hotkey", "ctrl+alt+space"))
        self.width = int(ui.get("width", 720))
        self.auto_hide = bool(ui.get("auto_hide", True))
        self.window = None
        self.icon = None
        self.visible = True
        self._task_lock = threading.Lock()
        self.running = False
        self._engine = None
        self._dictation = None
        self._mic = None
        self._dict_gen = 0  # sessão do ditado: Parar antes do load() cancela o start

    # --- Python -> JS -----------------------------------------------------------
    def js(self, fn: str, *args) -> None:
        if self.window is None:
            return
        try:
            self.window.evaluate_js(js_call(fn, *args))
        except Exception:
            pass

    # --- janela -----------------------------------------------------------------
    def show(self) -> None:
        if self.window is not None:
            self.window.show()
            self.visible = True
            self.js("focus")

    def hide(self) -> None:
        if self.window is not None:
            self.window.hide()
            self.visible = False

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    # --- agente -------------------------------------------------------------------
    def run_task(self, text: str) -> None:
        if not text:
            return
        if not self._task_lock.acquire(blocking=False):
            self.js("error", "já há uma tarefa em execução")
            return
        threading.Thread(target=self._task, args=(text,), daemon=True).start()

    def _task(self, text: str) -> None:
        from loop import run

        try:
            self.running = True
            self.js("running", text)
            if self.auto_hide:
                self.hide()
                time.sleep(0.3)  # hide é despachado; sem isto o 1º snapshot vê a Spotlight
            real = sys.stdout
            sys.stdout = LineTee(real, lambda ln: self.js("step", ln, classify(ln)))
            try:
                summary = run(text, self.cfg)
            finally:
                sys.stdout = real
            self.js("done", summary.get("result", "?"),
                    json.dumps(summary, ensure_ascii=False, indent=1))
        except Exception as e:
            self.js("error", f"{type(e).__name__}: {e}")
        finally:
            self.running = False
            self._task_lock.release()
            self.show()

    # --- ditado ---------------------------------------------------------------------
    def _ensure_dictation(self):
        if self._dictation is None:
            import stt

            self._engine = stt.build_engine(self.cfg)
            self._dictation = stt.build_dictation(
                self.cfg, self._engine,
                on_partial=lambda t: self.js("partial", t),
                on_final=self._on_final,
                on_error=lambda m: self.js("error", m))
            self._mic = stt.MicSource(self._dictation)
        return self._dictation

    def _on_final(self, text: str, send: bool) -> None:
        self.js("final", text, send)
        if send:
            self.run_task(text)

    def dictation_start(self) -> None:
        if self.running:
            return
        try:
            self._ensure_dictation()
            self._dict_gen += 1
            # carrega o modelo fora da thread de áudio; 1ª vez baixa ~74 MB
            threading.Thread(target=self._start_mic, args=(self._dict_gen,),
                             daemon=True).start()
        except Exception as e:
            self.js("error", f"ditado indisponível: {e} (uv sync --extra ui)")

    def _start_mic(self, gen: int) -> None:
        try:
            load = getattr(self._engine, "load", None)
            if load:
                load()
            if gen != self._dict_gen:
                return  # usuário clicou Parar enquanto o modelo carregava
            self._mic.start()
            self.js("partial", "")
        except Exception as e:
            self.js("error", f"microfone/modelo: {e}")

    def dictation_stop(self, send: bool) -> None:
        self._dict_gen += 1  # cancela um _start_mic pendente
        if self._mic is not None:
            self._mic.stop()
        if self._dictation is not None:
            self._dictation.stop(send=send)

    # --- tray -----------------------------------------------------------------------
    def _tray_image(self):
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((4, 4, 60, 60), radius=16, fill=(0, 120, 212, 255))
        d.rounded_rectangle((22, 22, 42, 42), radius=5, fill=(255, 255, 255, 235))
        return img

    def _tray(self) -> None:
        import pystray

        def quit_(icon, _item):
            icon.stop()
            self.dictation_stop(send=False)
            try:
                self.window.destroy()
            except Exception:
                pass

        menu = pystray.Menu(
            pystray.MenuItem("Mostrar / esconder", lambda *_: self.toggle(), default=True),
            pystray.MenuItem(f"Hotkey: {self.hotkey}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", quit_),
        )
        self.icon = pystray.Icon("copilot-road-runner", self._tray_image(),
                                 "copilot-road-runner", menu=menu)
        self.icon.run()

    # --- boot ----------------------------------------------------------------------
    def _geometry(self) -> tuple[int, int, int]:
        height = 400  # a área fora do card é transparente
        try:
            import ctypes

            u = ctypes.windll.user32
            sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
            return (sw - self.width) // 2, int(sh * 0.18), height
        except Exception:
            return 200, 160, height

    def _hotkey(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey(self.hotkey, self.toggle)
        except Exception as e:
            print(f"hotkey {self.hotkey} indisponível: {e}")

    def run(self) -> None:
        import webview

        x, y, h = self._geometry()
        self.window = webview.create_window(
            "copilot-road-runner", url=str(UI_HTML), js_api=JsApi(self),
            width=self.width, height=h, x=x, y=y, frameless=True, easy_drag=True,
            on_top=True, transparent=True, background_color="#000000",
            resizable=False)

        def on_closing():
            self.hide()
            return False  # X/Alt+F4 esconde; "Sair" fica na tray

        self.window.events.closing += on_closing
        threading.Thread(target=self._tray, daemon=True).start()
        self._hotkey()
        webview.start(gui="edgechromium")
        # janela destruída pela tray -> encerra tudo
        self.dictation_stop(send=False)
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
