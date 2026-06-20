"""FastAPI server exposing the iMessage memory networks to the web UI.

Boots one embedded Hindsight client at startup (pg0 + OpenRouter) and reuses it
across requests. Run via Doppler so OPENROUTER_API_KEY is injected:

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

from poc_demo.server import data
from recall.hindsight_runtime import embedded_hindsight

DEFAULT_BANK = os.environ.get("RECALL_BANK", "imessage-v0")

_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Boot the embedded Hindsight client once for the server's lifetime."""
    with embedded_hindsight() as client:
        _state["client"] = client
        yield
    _state.clear()


app = FastAPI(title="Recall demo API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report whether the embedded client is ready."""
    return {"status": "ok" if _state.get("client") else "starting", "bank": DEFAULT_BANK}


@app.get("/api/networks")
async def networks(bank: str = DEFAULT_BANK) -> dict[str, Any]:
    """Return all five memory networks for ``bank`` as JSON.

    The Hindsight client is synchronous and drives aiohttp on its own loop, so we
    run it in a worker thread to keep it off the server's event loop.
    """
    client = _state["client"]
    return await asyncio.to_thread(data.all_networks, client, bank)
