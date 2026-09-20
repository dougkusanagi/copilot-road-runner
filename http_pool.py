"""HTTP persistente F6: pool de clientes, cancelamento e medição de cache.

- Uma geração ativa por GPU inicialmente; filas curtas e cancelamento.
- Conexão reutilizada (keep-alive), cancelamento de HTTP, limites separados
  p/ carga/prefill/geração (via timeouts por fase quando o backend expõe);
  retries de inferência NUNCA repetem ações físicas (só HTTP aqui).
- Cachear prefixos se o backend suportar e medir hits; cliente persistente.
"""
from __future__ import annotations

import threading
import time

import httpx

import safety

_clients: dict[str, httpx.Client] = {}
_lock = threading.Lock()
_stats: dict[str, dict] = {}


def client_for(base_url: str, timeout_s: float) -> httpx.Client:
    """Cliente persistente por base_url (keep-alive; cria uma vez)."""
    key = f"{base_url}|{timeout_s}"
    with _lock:
        c = _clients.get(key)
        if c is None:
            c = httpx.Client(timeout=timeout_s, limits=httpx.Limits(
                max_connections=4, max_keepalive_connections=2))
            _clients[key] = c
            _stats[key] = {"requests": 0, "retries": 0, "cancelled": 0}
        return c


def post_json(base_url: str, path: str, payload: dict, timeout_s: float,
              retries: int = 2) -> tuple[dict, float]:
    """POST com retries só-HTTP (nunca repete ação física) e cancelamento.

    Retorna (json, ms_totais). Levanta a última exceção se esgotar.
    """
    key = f"{base_url}|{timeout_s}"
    client = client_for(base_url, timeout_s)
    last: Exception | None = None
    t0 = time.perf_counter()
    for attempt in range(retries + 1):
        if safety.stop_requested():
            with _lock:
                _stats[key]["cancelled"] += 1
            raise RuntimeError("cancelado (stop solicitado) antes do POST")
        try:
            with _lock:
                _stats[key]["requests"] += 1
            r = client.post(f"{base_url.rstrip('/')}{path}", json=payload)
            r.raise_for_status()
            ms = (time.perf_counter() - t0) * 1000
            return r.json(), ms
        except Exception as e:
            last = e
            retryable = isinstance(e, httpx.TimeoutException) or (
                isinstance(e, httpx.HTTPStatusError)
                and e.response is not None and e.response.status_code >= 500)
            if not retryable or attempt >= retries:
                break
            with _lock:
                _stats[key]["retries"] += 1
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"HTTP falhou: {last}")


def stats() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _stats.items()}


def close_all() -> None:
    with _lock:
        for c in _clients.values():
            try:
                c.close()
            except Exception:
                pass
        _clients.clear()
