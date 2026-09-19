"""Servidor próprio de modelos: baixa e sobe os 2 llama-server (planner+visão).

Meta: `uv run python main.py "..."` funciona SEM subir nada externo. O projeto
tem seu próprio runtime: na 1ª execução baixa o binário do `llama-server`
(llama.cpp, release Windows x64 CPU) e os GGUFs para `models/` (gitignored);
nas seguintes, só reusa. O "erro honesto" (loop.py) passa a valer só quando
algo de verdade falha (download, porta ocupada por servidor de outro modelo,
runtime ausente) — não quando ninguém subiu servidor externo.

Reuso: se a porta já tem um endpoint /v1/models vivo, usamos ele (seja de uma
execução anterior nossa, seja um llama-server que o usuário subiu apontado
para os mesmos GGUFs — não importa quem subiu). Porta ocupada SEM endpoint
vivo (ou com outro modelo) = erro honesto, nunca matamos processo alheio.
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
BIN_DIR = MODELS_DIR / "bin"

# Portas fora do padrão (config.json + AGENTS.md): não colidem com Ollama
# (11434), LM Studio (1234) nem OpenAI (443/80).
PLANNER_PORT = 8091
VISION_PORT = 8082

PLANNER_MODEL = "MiniCPM5-1B"
VISION_MODEL = "Vocaela-2-500M-1024R2"

# Fontes oficiais (model cards citados em planner.py/vocaela.py). URLs públicas
# (resolvidas sem token, conferidas por HEAD antes de implementar).
PLANNER_GGUF = {
    "file": "MiniCPM5-1B-Q4_K_M.gguf",  # ~657 MB
    "url": ("https://huggingface.co/openbmb/MiniCPM5-1B-GGUF/resolve/main/"
            "MiniCPM5-1B-Q4_K_M.gguf"),
}
VISION_GGUF = {
    "file": "Vocaela-2-500M-1024R2-Q8_0.gguf",  # ~437 MB
    "url": ("https://huggingface.co/vocaela/Vocaela-2-500M-1024R2-GGUF/resolve/main/"
            "Vocaela-2-500M-1024R2-Q8_0.gguf"),
}
VISION_MMPROJ = {
    "file": "mmproj-Vocaela-2-500M-1024R2-Q8_0.gguf",  # ~97 MB
    "url": ("https://huggingface.co/vocaela/Vocaela-2-500M-1024R2-GGUF/resolve/main/"
            "mmproj-Vocaela-2-500M-1024R2-Q8_0.gguf"),
}

# Release fixa do llama.cpp (binários Windows x64 CPU); atualize o tag de vez
# em quando. CPU-only de propósito: roda em qualquer PC; quem quiser GPU pode
# subir llama-server externo — o reuso por porta cobre isso.
LLAMA_TAG = "b11053"
LLAMA_ZIP_URL = ("https://github.com/ggml-org/llama.cpp/releases/download/"
                 f"{LLAMA_TAG}/llama-{LLAMA_TAG}-bin-win-cpu-x64.zip")
LLAMA_EXE = BIN_DIR / "llama-server.exe"

# Parâmetros conservadores p/ máquina comum (CPU). Overridable via config.json
# → seção "runtime" (auto_start, host, ngl p/ GPU, threads, ctx).
DEFAULT_NGL = 0
DEFAULT_THREADS = max(2, (os.cpu_count() or 4) // 2)
DEFAULT_CTX = 4096


def _split_host_port(base_url: str) -> tuple[str, int]:
    """Host/porta de um base_url OpenAI-compatible (default 80 sem porta)."""
    netloc = urllib.parse.urlsplit(
        base_url if "://" in base_url else f"http://{base_url}").netloc
    host, sep, port = netloc.rpartition(":")
    if not sep or not port.isdigit():
        return (netloc or "127.0.0.1"), 80
    return (host.strip("[]") or "127.0.0.1"), int(port)


def needs_local_serve(base_urls: tuple[str, ...]) -> bool:
    """True se TODOS os base_urls apontam p/ esta máquina (127.0.0.1/localhost).

    URLs remotas (ex.: HOST_IP do Sandbox) são gerenciadas por quem as expõe:
    não baixamos nada nem subimos processo aqui (evitaria 1,2 GB dentro do
    repo mapeado do Sandbox)."""
    if not base_urls or not all(base_urls):
        return False
    return all(_split_host_port(u)[0] in ("127.0.0.1", "localhost", "::1")
               for u in base_urls)


# --- infra ---------------------------------------------------------------------
def _download(url: str, dest: Path, min_bytes: int = 1024 * 1024,
              progress=print) -> Path:
    """Baixa url -> dest (atômico via .part). Rejeita resposta < min_bytes
    (página de erro do HF/redirect quebra silencioso)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "copilot-road-runner"})
        with urllib.request.urlopen(req, timeout=120) as r, part.open("wb") as f:
            total = r.headers.get("Content-Length")
            done = 0
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total and progress and done % (200 * 1024 * 1024) < 1024 * 1024:
                    progress(f"  {done / 1e6:.0f}/{int(total) / 1e6:.0f} MB")
        size = part.stat().st_size
        if size < min_bytes:
            raise RuntimeError(f"download suspeito ({size} bytes): {url}")
        part.replace(dest)
        return dest
    finally:
        part.unlink(missing_ok=True)


def _extract_zip(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    zip_path.unlink(missing_ok=True)  # ~230 MB: não guardar
    # O release empacota em subpasta (llama-<tag>-bin-win-cpu-x64/);
    # normaliza p/ BIN_DIR/llama-server.exe, que o resto do código espera.
    if not LLAMA_EXE.exists():
        for cand in dest.rglob("llama-server.exe"):
            if cand.resolve() != LLAMA_EXE.resolve():
                LLAMA_EXE.parent.mkdir(parents=True, exist_ok=True)
                cand.replace(LLAMA_EXE)
            break


def _endpoint_alive(base_url: str, timeout_s: float = 5.0) -> dict | None:
    """/v1/models vivo? Retorna {"models": [...]} ou None."""
    import httpx

    try:
        r = httpx.get(f"{base_url.rstrip('/')}/models", timeout=timeout_s)
        if r.status_code == 200:
            return {"models": [m.get("id", "?")
                               for m in r.json().get("data", [])]}
    except Exception:
        pass
    return None


def _port_in_use(host: str, port: int) -> bool:
    """connect-test (bind-test dá falso positivo no Windows via SO_REUSEADDR)."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


# --- assets (download único, gitignored em models/) ------------------------------
def ensure_assets(progress=print) -> dict:
    """Baixa o que falta (llama.cpp + GGUFs) e extrai. Idempotente.

    Retorna Paths {exe, planner_gguf, vision_gguf, mmproj}.
    Erro honesto (RuntimeError) se download/extração falhar.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if not LLAMA_EXE.exists():
        progress(f"baixando llama.cpp {LLAMA_TAG} (CPU x64, 1ª vez)...")
        zp = MODELS_DIR / "llama.zip"
        _download(LLAMA_ZIP_URL, zp, min_bytes=10_000_000, progress=progress)
        _extract_zip(zp, BIN_DIR)
        if not LLAMA_EXE.exists():
            raise RuntimeError(
                f"llama-server.exe não apareceu em {BIN_DIR} após extrair {LLAMA_ZIP_URL}")

    inv: dict[str, tuple[Path, dict, int]] = {
        "planner_gguf": (MODELS_DIR / PLANNER_GGUF["file"], PLANNER_GGUF, 100_000_000),
        "vision_gguf": (MODELS_DIR / VISION_GGUF["file"], VISION_GGUF, 100_000_000),
        "mmproj": (MODELS_DIR / VISION_MMPROJ["file"], VISION_MMPROJ, 10_000_000),
    }
    assets: dict[str, Path] = {"exe": LLAMA_EXE}
    for key, (dest, src, min_bytes) in inv.items():
        if not dest.exists():
            progress(f"baixando {src['file']} (1ª vez)...")
            _download(src["url"], dest, min_bytes=min_bytes, progress=progress)
        assets[key] = dest
    return assets


# --- spawn -----------------------------------------------------------------------
def _server_args(role: str, gguf: Path, mmproj: Path | None, port: int,
                 cfg: dict) -> list[str]:
    rt = cfg.get("runtime", {})
    host = str(rt.get("host", "127.0.0.1"))
    ngl = int(rt.get("ngl", DEFAULT_NGL))
    threads = int(rt.get("threads", DEFAULT_THREADS))
    if threads <= 0:
        threads = DEFAULT_THREADS
    ctx = int(rt.get("ctx", DEFAULT_CTX))
    args = [str(LLAMA_EXE), "-m", str(gguf), "--host", host,
            "--port", str(port), "-c", str(ctx), "-t", str(threads), "-ngl", str(ngl)]
    if mmproj is not None:
        args += ["--mmproj", str(mmproj)]
    if role == "planner":
        # jinja: o template oficial do MiniCPM5 (planner.py conta com ele p/
        # chat_template_kwargs.enable_thinking).
        args += ["--jinja"]
    return args


def _spawn_one(role: str, base_url: str, port: int, assets: dict, cfg: dict,
               progress=print) -> subprocess.Popen:
    gguf = assets["planner_gguf" if role == "planner" else "vision_gguf"]
    mmproj = assets["mmproj"] if role == "vision" else None
    args = _server_args(role, gguf, mmproj, port, cfg)
    log = MODELS_DIR / f"llama-server-{role}.log"
    host = str(cfg.get("runtime", {}).get("host", "127.0.0.1"))
    progress(f"subindo {role} ({Path(gguf).name}) em {host}:{port}...")
    with log.open("ab") as f:
        f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n".encode())
        f.flush()
        proc = subprocess.Popen(args, stdout=f, stderr=f,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not _endpoint_alive(base_url, timeout_s=180.0):
        tail = ""
        try:
            tail = log.read_text(encoding="utf-8", errors="replace")[-500:]
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server ({role}) saiu cedo (code {proc.returncode}). "
                               f"log: {log}\n{tail}")
        proc.kill()
        raise RuntimeError(f"llama-server ({role}) não respondeu em 180s. log: {log}\n{tail}")
    return proc


def ensure_servers(base_urls: tuple[str, str], cfg: dict,
                   progress=print) -> dict:
    """Garante os 2 endpoints vivos; baixa assets e sobe llama-server se preciso.

    - Endpoint vivo na porta -> REUSA (nossa execução anterior ou servidor
      externo; quem subiu não importa).
    - Porta ocupada sem endpoint (ou inacessível) -> erro honesto (não matamos
      processo alheio).
    - Porta livre -> baixa assets (1ª vez) e sobe nosso llama-server.

    Retorna {"planner": Popen|None, "vision": Popen|None} (None = reusado).
    """
    out: dict = {"planner": None, "vision": None}
    needed: dict[str, tuple[str, int]] = {}

    for role, base_url in zip(("planner", "vision"), base_urls):
        alive = _endpoint_alive(base_url)
        if alive:
            progress(f"{role}: reusando {base_url} (modelos={alive['models']})")
            continue
        host, port = _split_host_port(base_url)
        if _port_in_use(host, port):
            raise RuntimeError(
                f"porta {port} ocupada sem endpoint /v1/models acessível ({role}); "
                f"feche o processo ou aponte {role}.base_url para ele. Log: "
                f"{MODELS_DIR / f'llama-server-{role}.log'}")
        needed[role] = (base_url, port)

    if needed:
        progress("modelos não estão no ar; garantindo runtime local...")
        assets = ensure_assets(progress=progress)
        for role, (base_url, port) in needed.items():
            out[role] = _spawn_one(role, base_url, port, assets, cfg, progress=progress)
    return out


def stop_servers(procs: dict) -> None:
    """Encerra os llama-server que NÓS subimos nesta execução (reusados: nunca)."""
    for role, proc in procs.items():
        if proc is None:
            continue
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def main() -> None:
    """CLI: sobe os 2 llama-server e fica no ar (Ctrl+C para).

    Uso: uv run python -m server [--host 0.0.0.0]
    O loop (main.py) já sobe sozinho em 127.0.0.1; a CLI existe p/ deixar os
    endpoints permanentes ou acessíveis ao Sandbox (--host 0.0.0.0).
    """
    import argparse

    import config as cfgmod

    ap = argparse.ArgumentParser(description="Runtime próprio dos 2 modelos")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind dos llama-server (127.0.0.1 ou 0.0.0.0 p/ Sandbox)")
    ap.add_argument("--config", default="config.json")
    args = ap.parse_args()

    cfg = cfgmod.load(args.config)
    cfg.setdefault("runtime", {})["host"] = args.host
    base_urls = (f"http://127.0.0.1:{PLANNER_PORT}/v1",
                 f"http://127.0.0.1:{VISION_PORT}/v1")
    if args.host != "127.0.0.1":
        # bind liberado: os endpoints externos ficam no IP da máquina (p/ Sandbox)
        import socket as _s

        ip = ""
        try:
            with _s.socket(_s.AF_INET, _s.SOCK_DGRAM) as sk:
                sk.connect(("8.8.8.8", 80))
                ip = sk.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        base_urls = (f"http://{ip}:{PLANNER_PORT}/v1", f"http://{ip}:{VISION_PORT}/v1")

    assets = ensure_assets()
    procs = {"planner": None, "vision": None}
    try:
        for role, base_url in zip(("planner", "vision"), base_urls):
            alive = _endpoint_alive(base_url)
            if alive:
                print(f"{role}: já no ar em {base_url} (reuso)")
                continue
            _, port = _split_host_port(base_url)
            procs[role] = _spawn_one(role, base_url, port, assets, cfg)
            want = PLANNER_MODEL if role == "planner" else VISION_MODEL
            print(f"{role}: {base_url} (modelos=[{want}])")
        print("Ctrl+C para encerrar.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nencerrando...")
    finally:
        stop_servers(procs)


if __name__ == "__main__":
    main()
