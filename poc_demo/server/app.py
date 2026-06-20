"""FastAPI server exposing the iMessage memory networks to the web UI.

Boots the embedded Hindsight server once at startup (pg0 + OpenRouter, on its own
background thread) and keeps its base URL. Each request builds a *fresh* sync client
inside a worker thread, so the client's aiohttp session and the loop that drives it
are created together in that thread — mirroring the working CLI. Sharing one client
across the server's event loop and worker threads triggers aiohttp's
"Timeout context manager should be used inside a task" error.

Run via Doppler so OPENROUTER_API_KEY is injected:

    doppler run --project berkeley-hackathon --config dev -- \\
        .venv/bin/python -m uvicorn poc_demo.server.app:app --port 8000
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from hindsight_client import Hindsight

from poc_demo.server import data
from recall.hindsight_runtime import embedded_hindsight

DEFAULT_BANK = os.environ.get("RECALL_BANK", "imessage-v0")

_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Boot the embedded Hindsight server once and capture its base URL."""
    with embedded_hindsight() as client:
        _state["base_url"] = client._base_url
        yield
    _state.clear()


app = FastAPI(title="Recall demo API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _fetch_networks(base_url: str, bank: str) -> dict[str, Any]:
    """Build a fresh client in this thread and gather all networks (blocking)."""
    client = Hindsight(base_url=base_url)
    try:
        return data.all_networks(client, bank)
    finally:
        client.close()


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report whether the embedded server is ready."""
    return {"status": "ok" if _state.get("base_url") else "starting", "bank": DEFAULT_BANK}


@app.get("/api/networks")
async def networks(bank: str = DEFAULT_BANK) -> dict[str, Any]:
    """Return all five memory networks for ``bank`` as JSON.

    Runs a fresh sync client in a worker thread so its aiohttp loop is local to
    that thread.
    """
    base_url = _state["base_url"]
    return await asyncio.to_thread(_fetch_networks, base_url, bank)
