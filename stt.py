"""Ditado ao vivo (STT local): o texto aparece ENQUANTO o usuário fala.

Whisper não é streaming; a técnica é retranscrever o buffer da fala atual
a cada `partial_every_ms` (parcial) e, ao detectar silêncio contínuo por
`silence_ms`, transcrever de novo (final) e — se `auto_send` — enviar.

Camadas (a lógica é pura, testável sem mic/modelo):
  Engine          transcribe(samples float32 16k) -> str   (faster-whisper)
  Dictation       feed(chunk, now) -> on_partial / on_final  (pura)
  MicSource       sounddevice -> Dictation.feed em thread própria

Modelo padrão: faster-whisper `base` int8 (~74 MB, CTranslate2, sem torch),
VAD Silero embutido (`vad_filter`). Trocar o engine = trocar SÓ este arquivo.
"""
from __future__ import annotations

import math
import threading
import time
from array import array
from typing import Callable, Protocol

SAMPLE_RATE = 16000


class Engine(Protocol):
    def transcribe(self, samples: array) -> str: ...


class FasterWhisperEngine:
    """Adapter do faster-whisper (CTranslate2). Carrega o modelo na 1ª chamada."""

    def __init__(self, model: str = "base", compute_type: str = "int8",
                 language: str = "pt", device: str = "cpu"):
        self.model_name = model
        self.compute_type = compute_type
        self.language = language
        self.device = device
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device=self.device,
                                           compute_type=self.compute_type)

    def transcribe(self, samples: array) -> str:
        import numpy as np

        self.load()
        audio = np.frombuffer(samples.tobytes(), dtype=np.float32)
        if audio.size < SAMPLE_RATE // 4:  # < 250 ms: nada útil
            return ""
        segments, _info = self._model.transcribe(
            audio, language=self.language, beam_size=1, vad_filter=True,
            without_timestamps=True, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


def rms(chunk: array) -> float:
    if not len(chunk):
        return 0.0
    return math.sqrt(sum(x * x for x in chunk) / len(chunk))


class Dictation:
    """Máquina de estados do ditado. Chame feed() com blocos de áudio.

    Callbacks:
      on_partial(text)         texto provisório (pode mudar)
      on_final(text, send)     texto definitivo; send=True quando veio de
                               silêncio com auto_send ou de stop(send=True)
      on_error(msg)            engine falhou (modelo ausente...); NUNCA vira
                               texto nem é enviado
    """

    def __init__(self, engine: Engine, on_partial: Callable[[str], None],
                 on_final: Callable[[str, bool], None], *,
                 on_error: Callable[[str], None] | None = None,
                 partial_every_ms: int = 1000, silence_ms: int = 1500,
                 silence_rms: float = 0.01, max_utterance_s: int = 30,
                 auto_send: bool = True, sample_rate: int = SAMPLE_RATE):
        self.engine = engine
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_error = on_error or (lambda _m: None)
        self.failed = False
        self.partial_every = partial_every_ms / 1000.0
        self.silence = silence_ms / 1000.0
        self.silence_rms = silence_rms
        self.max_samples = max_utterance_s * sample_rate
        self.auto_send = auto_send
        self._buf = array("f")
        self._lock = threading.Lock()
        self.active = False
        self.text = ""
        self._had_voice = False
        self._last_voice = 0.0
        self._last_partial = 0.0
        self._started = 0.0

    # --- ciclo -------------------------------------------------------------
    def start(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._buf = array("f")
            self.text = ""
            self.failed = False
            self._had_voice = False
            self._last_voice = now
            self._last_partial = now
            self._started = now
            self.active = True

    def feed(self, chunk: array, now: float | None = None) -> None:
        """Bloco de áudio float32 mono 16 kHz. Pode disparar parcial/final."""
        if not self.active:
            return
        now = time.monotonic() if now is None else now
        with self._lock:
            self._buf.extend(chunk)
            if len(self._buf) > self.max_samples:
                del self._buf[:len(self._buf) - self.max_samples]
            if rms(chunk) >= self.silence_rms:
                self._had_voice = True
                self._last_voice = now
            due_partial = self._had_voice and now - self._last_partial >= self.partial_every
            due_final = self._had_voice and now - self._last_voice >= self.silence
        if due_final:
            self._finish(send=self.auto_send, reason="silence")
            return
        if due_partial:
            self._last_partial = now
            text = self._safe_transcribe()
            if text and text != self.text:
                self.text = text
                self.on_partial(text)

    def stop(self, send: bool = False) -> str:
        """Parar (send=False: texto fica editável) ou Enviar (send=True)."""
        if not self.active:
            return self.text
        return self._finish(send=send, reason="user")

    # --- interno -----------------------------------------------------------
    def _safe_transcribe(self) -> str:
        with self._lock:
            snapshot = array("f", self._buf)
        try:
            return self.engine.transcribe(snapshot)
        except Exception as e:  # modelo indisponível: não derruba a UI
            self.failed = True
            self.on_error(f"stt: {type(e).__name__}: {str(e)[:120]}")
            return self.text  # nunca texto de erro como instrução

    def _finish(self, send: bool, reason: str) -> str:
        with self._lock:
            if not self.active:
                return self.text
            self.active = False
        text = self._safe_transcribe() if self._had_voice else ""
        self.text = text or self.text
        # engine falhou nesta sessão: entrega o que houver, mas NÃO envia
        self.on_final(self.text, bool(send and self.text and not self.failed))
        return self.text


class MicSource:
    """Captura do microfone (sounddevice) -> Dictation.feed em thread própria.

    O callback do PortAudio só enfileira; a transcrição roda na thread
    consumidora (nunca dentro do callback de áudio).
    """

    def __init__(self, dictation: Dictation, sample_rate: int = SAMPLE_RATE,
                 block_ms: int = 100):
        self.d = dictation
        self.sample_rate = sample_rate
        self.blocksize = sample_rate * block_ms // 1000
        self._stream = None
        self._thread: threading.Thread | None = None
        self._q: list[array] = []
        self._cv = threading.Condition()
        self._running = False

    def _callback(self, indata, frames, _time, status) -> None:
        chunk = array("f")
        chunk.frombytes(indata[:, 0].astype("float32").tobytes())
        with self._cv:
            self._q.append(chunk)
            self._cv.notify()

    def _worker(self) -> None:
        while True:
            with self._cv:
                while not self._q and self._running:
                    self._cv.wait(0.2)
                if not self._running and not self._q:
                    return
                chunk = self._q.pop(0)
            self.d.feed(chunk)
            if not self.d.active:  # silêncio finalizou: para de capturar
                self.stop()
                return

    def start(self) -> None:
        import sounddevice as sd

        with self._cv:
            self._q.clear()  # sem restos da sessão anterior
        self.d.start()
        self._running = True
        self._stream = sd.InputStream(samplerate=self.sample_rate, channels=1,
                                      dtype="float32", blocksize=self.blocksize,
                                      callback=self._callback)
        self._stream.start()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        with self._cv:
            self._cv.notify_all()
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass


def build_engine(cfg: dict) -> Engine:
    sc = cfg.get("stt", {})
    name = sc.get("engine", "faster-whisper")
    if name == "faster-whisper":
        return FasterWhisperEngine(model=sc.get("model", "base"),
                                   compute_type=sc.get("compute_type", "int8"),
                                   language=sc.get("language", "pt"))
    raise ValueError(f"stt.engine desconhecido: {name!r}")


def build_dictation(cfg: dict, engine: Engine, on_partial, on_final,
                    on_error=None) -> Dictation:
    sc = cfg.get("stt", {})
    return Dictation(engine, on_partial, on_final, on_error=on_error,
                     partial_every_ms=int(sc.get("partial_every_ms", 1000)),
                     silence_ms=int(sc.get("silence_ms", 1500)),
                     silence_rms=float(sc.get("silence_rms", 0.01)),
                     max_utterance_s=int(sc.get("max_utterance_s", 30)),
                     auto_send=bool(sc.get("auto_send", True)))
