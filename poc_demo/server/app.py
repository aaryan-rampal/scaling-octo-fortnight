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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from hindsight_client import Hindsight

from pipeline.explain import LLMWhyExplainer, explain_principle
from poc_demo.server import data
from poc_demo.server.capsules import (
    DEFAULT_MEDIA_ROOT,
    UnsupportedMediaError,
    build_capsule,
)
from runtime.hindsight import embedded_hindsight
from storage.store import CapsuleStore
from storage.trace import open_db

DEFAULT_BANK = os.environ.get("RECALL_BANK", "imessage-v0")

#: SQLite provenance DB the principle trace-back / explain endpoints read.
#: Read-only; defaults to the sample slice. Override with RECALL_TRACE_DB.
TRACE_DB = os.environ.get("RECALL_TRACE_DB", "data/derek_handoff/derek_sample.db")

_state: dict[str, Any] = {}

#: The SQLite raw_data store. One instance for the process; each method opens its
#: own short-lived connection so it is safe across worker threads.
_store = CapsuleStore()

#: Where capsule media binaries are written. Module-level so tests can point it
#: at a temp dir without touching the upload-handling code.
MEDIA_ROOT = DEFAULT_MEDIA_ROOT


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
    allow_origins=["http://localhost:5173", "http://localhost:4321"],
    allow_methods=["GET", "POST"],
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


# ---- principle trace-back + "why" --------------------------------------
#
# Reads the materialised provenance graph in SQLite (read-only) and explains a
# principle from its own evidence. The trace is deterministic; only the "why"
# text costs an LLM call, so run under Doppler for the explain route.


def _list_principles() -> list[dict[str, Any]]:
    """Return the principles in TRACE_DB, highest confidence first (blocking)."""
    conn = open_db(TRACE_DB)
    try:
        rows = conn.execute(
            "SELECT id, text, confidence FROM principles ORDER BY confidence DESC"
        ).fetchall()
        return [{"id": r["id"], "text": r["text"], "confidence": r["confidence"]} for r in rows]
    finally:
        conn.close()


def _explain_principle(principle_id: str) -> dict[str, Any] | None:
    """Trace + explain one principle (blocking). ``None`` if no such id."""
    conn = open_db(TRACE_DB)
    try:
        return explain_principle(conn, principle_id, LLMWhyExplainer())
    finally:
        conn.close()


@app.get("/api/principles")
async def list_principles() -> dict[str, Any]:
    """List principle ids + text for the demo to render (no LLM call)."""
    if not Path(TRACE_DB).exists():
        raise HTTPException(status_code=503, detail=f"trace DB not found: {TRACE_DB}")
    return {"principles": await asyncio.to_thread(_list_principles)}


@app.get("/api/principles/{principle_id}/why")
async def principle_why(principle_id: str) -> dict[str, Any]:
    """Trace a principle to its evidence and return an LLM explanation of why.

    Returns the principle, its backing memories with their raw events, and a
    ``why`` string. 404 when the id is unknown; 503 when the DB or API key is
    missing. Blocking work runs in a worker thread.
    """
    if not Path(TRACE_DB).exists():
        raise HTTPException(status_code=503, detail=f"trace DB not found: {TRACE_DB}")
    try:
        result = await asyncio.to_thread(_explain_principle, principle_id)
    except RuntimeError as exc:  # OPENROUTER_API_KEY not set (run under Doppler)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="principle not found")
    return result


# ---- capsule write-path (active raw_data) --------------------------------
#
# Persists user-created capsules (place + media) to the SQLite store. Conversion
# to canonical Events + Hindsight retain + the swarm is the next stage and is not
# done here — see TIME_CAPSULE_FLYWHEEL.md. The store is the seam where that
# downstream work picks the capsule up.


def _create_capsule(
    place_name: str,
    lat: float | None,
    lng: float | None,
    uploads: list[tuple[str, bytes, str | None]],
) -> dict[str, Any]:
    """Build, persist, and serialize a capsule (blocking)."""
    capsule = build_capsule(place_name, lat, lng, uploads, media_root=MEDIA_ROOT)
    _store.add_capsule(capsule)
    return capsule.to_dict()


@app.post("/api/capsules", status_code=201)
async def create_capsule(
    place_name: str = Form(...),
    lat: float | None = Form(None),
    lng: float | None = Form(None),
    media: list[UploadFile] = File(default=[]),  # noqa: B008 — FastAPI param marker
) -> dict[str, Any]:
    """Create a capsule from a place and uploaded media (multipart/form-data).

    Files are saved to disk; metadata is persisted to SQLite. File I/O runs in a
    worker thread so the event loop is never blocked.
    """
    if not place_name.strip():
        raise HTTPException(status_code=422, detail="place_name is required")
    uploads = [(f.filename or "upload", await f.read(), f.content_type) for f in media]
    try:
        return await asyncio.to_thread(_create_capsule, place_name, lat, lng, uploads)
    except UnsupportedMediaError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc


@app.get("/api/capsules")
async def list_capsules() -> dict[str, Any]:
    """Return all stored capsules, newest first."""
    capsules = await asyncio.to_thread(_store.list_capsules)
    return {"capsules": [c.to_dict() for c in capsules]}


@app.get("/api/capsules/{capsule_id}")
async def get_capsule(capsule_id: str) -> dict[str, Any]:
    """Return a single capsule by id, or 404 if it does not exist."""
    capsule = await asyncio.to_thread(_store.get_capsule, capsule_id)
    if capsule is None:
        raise HTTPException(status_code=404, detail="capsule not found")
    return capsule.to_dict()
