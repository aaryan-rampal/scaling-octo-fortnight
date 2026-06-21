"""Embedded Hindsight runtime backed by OpenRouter.

Boots an in-process Hindsight API server (FastAPI + uvicorn) on top of an
embedded PostgreSQL instance (pg0), configured to use OpenRouter for both the
LLM and embeddings. Exposes a context manager that yields a connected client
and tears everything down on exit.
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import uvicorn
from hindsight_client import Hindsight

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL = "google/gemini-3.5-flash"
DEFAULT_EMBEDDINGS_MODEL = "qwen/qwen3-embedding-8b"

# qwen3-embedding-8b is natively 4096-dim, but pgvector's HNSW index caps at 2000.
# The model is Matryoshka-trained, so a 2000-dim prefix stays meaningful; we route
# through LiteLLM (which forwards a ``dimensions`` request to OpenRouter) and
# truncate to this. The embedded pg0 ships only pgvector (no vchord/pgvectorscale),
# so staying <= 2000 is what makes qwen usable here at all.
EMBEDDINGS_TRUNCATE_DIM = 2000

_HOST = "127.0.0.1"
_STARTUP_TIMEOUT_S = 120.0
_SHUTDOWN_TIMEOUT_S = 30.0


def _pick_free_port() -> int:
    """Bind to an ephemeral port and return it for uvicorn to reuse."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return sock.getsockname()[1]


def _apply_openrouter_env(api_key: str, llm_model: str, embeddings_model: str) -> None:
    """Configure Hindsight via env vars so get_config() points at OpenRouter.

    The engine reads provider configuration from the process environment at
    construction time, so this must run before the MemoryEngine is built.
    """
    env = {
        "HINDSIGHT_API_DATABASE_URL": "pg0",
        "HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP": "true",
        "HINDSIGHT_API_WORKER_ENABLED": "false",
        # LLM via OpenRouter (OpenAI-compatible chat completions).
        "HINDSIGHT_API_LLM_PROVIDER": "openai",
        "HINDSIGHT_API_LLM_API_KEY": api_key,
        "HINDSIGHT_API_LLM_MODEL": llm_model,
        "HINDSIGHT_API_LLM_BASE_URL": OPENROUTER_BASE_URL,
        # Embeddings via LiteLLM → OpenRouter, so we can pass a truncated
        # ``dimensions`` (the plain openrouter provider does not forward it).
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "litellm-sdk",
        "HINDSIGHT_API_EMBEDDINGS_LITELLM_SDK_API_KEY": api_key,
        "HINDSIGHT_API_EMBEDDINGS_LITELLM_SDK_MODEL": f"openai/{embeddings_model}",
        "HINDSIGHT_API_EMBEDDINGS_LITELLM_SDK_API_BASE": OPENROUTER_BASE_URL,
        "HINDSIGHT_API_EMBEDDINGS_LITELLM_SDK_OUTPUT_DIMENSIONS": str(EMBEDDINGS_TRUNCATE_DIM),
        # No neural reranker: RRF passthrough needs no model or external call.
        "HINDSIGHT_API_RERANKER_PROVIDER": "rrf",
    }
    os.environ.update(env)


def _build_app():
    """Construct the FastAPI app and its MemoryEngine from the current env."""
    from hindsight_api.config import get_config
    from hindsight_api.engine.memory_engine import MemoryEngine
    from hindsight_api.main import create_app

    config = get_config()
    engine = MemoryEngine(run_migrations=config.run_migrations_on_startup)
    return create_app(engine, http_api_enabled=True, initialize_memory=True)


def _wait_until_ready(base_url: str, timeout_s: float) -> None:
    """Poll the server's /health endpoint until it responds or times out."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=5.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(
        f"Embedded Hindsight did not become ready within {timeout_s:.0f}s "
        f"(last error: {last_error})"
    )


@contextlib.contextmanager
def embedded_hindsight(
    *,
    llm_model: str = DEFAULT_LLM_MODEL,
    embeddings_model: str = DEFAULT_EMBEDDINGS_MODEL,
) -> Iterator[Hindsight]:
    """Run an embedded Hindsight server and yield a connected client.

    Boots an in-process FastAPI server on an embedded PostgreSQL database, wired
    to OpenRouter for both LLM completions and embeddings. The reader's
    ``OPENROUTER_API_KEY`` environment variable supplies credentials. The server
    runs on a background thread and is shut down cleanly when the context exits.

    Args:
        llm_model: OpenRouter model id used for retain/recall reasoning.
        embeddings_model: OpenRouter model id used for vector embeddings.

    Yields:
        A :class:`hindsight_client.Hindsight` client pointed at the local server.

    Raises:
        RuntimeError: If ``OPENROUTER_API_KEY`` is unset or the server fails to
            start within the readiness timeout.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in the environment")

    _apply_openrouter_env(api_key, llm_model, embeddings_model)

    port = _pick_free_port()
    base_url = f"http://{_HOST}:{port}"

    app = _build_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host=_HOST, port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="hindsight-embedded", daemon=True)
    thread.start()

    client: Hindsight | None = None
    try:
        _wait_until_ready(base_url, _STARTUP_TIMEOUT_S)
        client = Hindsight(base_url=base_url)
        yield client
    finally:
        if client is not None:
            client.close()
        server.should_exit = True
        thread.join(timeout=_SHUTDOWN_TIMEOUT_S)
