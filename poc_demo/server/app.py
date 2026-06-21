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

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from hindsight_client import Hindsight

from poc_demo.server import data
from poc_demo.server.capsules import (
    DEFAULT_MEDIA_ROOT,
    UnsupportedMediaError,
    build_capsule,
)
from runtime.hindsight import embedded_hindsight
from storage.store import CapsuleStore

DEFAULT_BANK = os.environ.get("RECALL_BANK", "imessage-v0")

#: Shared-secret passcode for the local-first auth gate. When set (via
#: ``RECALL_TOKEN`` or ``recall serve --token``), every protected request must
#: send a matching ``X-Recall-Token`` header — the passcode the UI's lock screen
#: collects. When unset, the app is open (convenient for laptop-only local dev).
#: This is what makes it safe to expose the laptop over a tunnel for mobile: the
#: data stays local, and only someone with the passcode can reach it.
RECALL_TOKEN = os.environ.get("RECALL_TOKEN") or None


#: Paths reachable without the passcode: the lock screen probes health, and the
#: static UI assets (the lock screen itself) must load so the user can enter it.
_OPEN_PATHS = ("/api/health",)


def _is_protected(path: str) -> bool:
    """Whether a request path requires the passcode (API + media; not health)."""
    if path in _OPEN_PATHS:
        return False
    return path.startswith("/api/") or path.startswith("/media/")


_state: dict[str, Any] = {}

#: The SQLite raw_data store. One instance for the process; each method opens its
#: own short-lived connection so it is safe across worker threads.
_store = CapsuleStore()

#: Where capsule media binaries are written. Module-level so tests can point it
#: at a temp dir without touching the upload-handling code.
MEDIA_ROOT = DEFAULT_MEDIA_ROOT


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Boot the embedded Hindsight server, degrading gracefully if it can't start.

    Hindsight (memory networks) needs OpenRouter, so it may be unavailable in a
    keyless local/mobile run. The capsule write path — upload → SQLite → media —
    needs none of that, so when the boot fails we log it, leave
    ``_state["base_url"]`` unset, and let the server come up anyway. Only
    ``/api/networks`` degrades; capsule creation, listing, and media all work.
    """
    try:
        with embedded_hindsight() as client:
            _state["base_url"] = client._base_url
            yield
    except Exception as exc:
        print(f"[recall] Hindsight unavailable ({exc}); memory networks disabled.")
        _state["base_url"] = None
        yield
    finally:
        _state.clear()


app = FastAPI(title="Recall demo API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def passcode_gate(request: Request, call_next):
    """Gate protected paths behind the shared-secret passcode.

    When ``RECALL_TOKEN`` is set, requests to ``/api/*`` (except health) and
    ``/media/*`` must send a matching ``X-Recall-Token`` header — the passcode
    the UI's lock screen collects. This is what makes exposing the laptop over a
    tunnel safe: data stays local and only the passcode-holder gets in. When no
    token is configured, the gate is a no-op (laptop-only local dev).
    """
    if RECALL_TOKEN is not None and _is_protected(request.url.path):
        # Header for API calls; ?t= query param for media (<img>/<video> can't
        # send headers).
        supplied = request.headers.get("x-recall-token") or request.query_params.get("t")
        if supplied != RECALL_TOKEN:
            return JSONResponse(
                status_code=401, content={"detail": "invalid or missing passcode"}
            )
    return await call_next(request)


# Serve uploaded capsule media at /media/<file_path>, which is the URL the UI
# builds for photos/videos. The directory is created up front so the mount works
# even before the first upload.
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")


def _fetch_networks(base_url: str, bank: str) -> dict[str, Any]:
    """Build a fresh client in this thread and gather all networks (blocking)."""
    client = Hindsight(base_url=base_url)
    try:
        return data.all_networks(client, bank)
    finally:
        client.close()


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Report server readiness and whether memory networks are available.

    ``memory`` is ``False`` when Hindsight could not boot (e.g. no OpenRouter
    key); the capsule write path is unaffected, so ``status`` is still ``ok``.
    """
    return {
        "status": "ok",
        "bank": DEFAULT_BANK,
        "memory": _state.get("base_url") is not None,
        "auth_required": RECALL_TOKEN is not None,
    }


@app.get("/api/networks")
async def networks(bank: str = DEFAULT_BANK) -> dict[str, Any]:
    """Return all memory networks for ``bank``, or 503 if Hindsight is disabled.

    Runs a fresh sync client in a worker thread so its aiohttp loop is local to
    that thread. When Hindsight did not boot (keyless local run), returns 503 so
    the UI can fall back to seed data rather than erroring.
    """
    base_url = _state.get("base_url")
    if base_url is None:
        raise HTTPException(status_code=503, detail="memory networks unavailable")
    return await asyncio.to_thread(_fetch_networks, base_url, bank)


# ---- capsule write-path (active raw_data) --------------------------------
#
# Persists user-created capsules (place + media) to the SQLite store AND projects
# each into the unified ``events`` table as a canonical Event (source="capsule"),
# so capsules ride the same provenance path as the passive sources. Hindsight
# retain + the agentic workflow that consumes these events is the next stage and
# is a future deliverable — see TIME_CAPSULE_FLYWHEEL.md.


def _note_from_uploads(uploads: list[tuple[str, bytes, str | None]]) -> str | None:
    """Extract the journal note text from a ``text/*`` upload, if present.

    The UI attaches the user's written reflection as a ``text/plain`` file. We
    have its bytes in hand here, so we can surface that authored text as the
    event's ``content`` without re-reading from disk.
    """
    for _filename, content, content_type in uploads:
        if content_type and content_type.startswith("text/"):
            text = content.decode("utf-8", "replace").strip()
            if text:
                return text
    return None


def _create_capsule(
    place_name: str,
    lat: float | None,
    lng: float | None,
    uploads: list[tuple[str, bytes, str | None]],
) -> dict[str, Any]:
    """Build the capsule, persist it, project it to a canonical event, return it.

    A capsule is persisted twice on purpose: to the ``capsules``/``media`` tables
    (the structured write path the UI reads back), **and** as a canonical
    :class:`~core.schema.Event` in the unified ``events`` table via
    :meth:`Capsule.to_event`. The latter puts the capsule on the same provenance
    path as the passive sources, so it is a traceable raw_data row ready to rise
    into memory. (The agentic workflow that consumes it is a future deliverable.)
    """
    capsule = build_capsule(place_name, lat, lng, uploads, media_root=MEDIA_ROOT)
    _store.add_capsule(capsule)
    _store.add_events([capsule.to_event(note=_note_from_uploads(uploads))])
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
