"""Standalone app: capsule write-path + the new index.html UI.

No Hindsight / OpenRouter / Doppler needed. Only requires:
    pip3 install fastapi "uvicorn[standard]" python-multipart

Run from the repo root:
    PYTHONPATH=src python3 -m uvicorn poc_demo.server.capsule_app:app --reload --port 8000

Then open http://localhost:8000

For memory networks / principles (needs OpenRouter key via Doppler):
    doppler run --project berkeley-hackathon --config dev -- python -m cli serve --port 8000
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from poc_demo.server.capsules import DEFAULT_MEDIA_ROOT, UnsupportedMediaError, build_capsule
from storage.store import CapsuleStore

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Repo root is three levels up from  poc_demo/server/capsule_app.py
_REPO_ROOT  = Path(__file__).parent.parent.parent
_INDEX_HTML = _REPO_ROOT / "index.html"
_TESTER_HTML = Path(__file__).parent / "static" / "capsule_tester.html"

MEDIA_ROOT = DEFAULT_MEDIA_ROOT

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------

app = FastAPI(title="Recall — Capsule API (standalone)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Media static files
# ---------------------------------------------------------------------------

MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")

# ---------------------------------------------------------------------------
# Shared store (one instance; each method opens its own short-lived connection)
# ---------------------------------------------------------------------------

_store = CapsuleStore()

# ---------------------------------------------------------------------------
# Capsule handlers (inlined from app.py — no hindsight dependency)
# ---------------------------------------------------------------------------

def _note_from_uploads(uploads: list[tuple[str, bytes, str | None]]) -> str | None:
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
    capsule = build_capsule(place_name, lat, lng, uploads, media_root=MEDIA_ROOT)
    _store.add_capsule(capsule)
    _store.add_events([capsule.to_event(note=_note_from_uploads(uploads))])
    return capsule.to_dict()


@app.post("/api/capsules", status_code=201)
async def create_capsule(
    place_name: str = Form(...),
    lat: float | None = Form(None),
    lng: float | None = Form(None),
    media: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    if not place_name.strip():
        raise HTTPException(status_code=422, detail="place_name is required")
    uploads = [(f.filename or "upload", await f.read(), f.content_type) for f in media]
    try:
        return await asyncio.to_thread(_create_capsule, place_name, lat, lng, uploads)
    except UnsupportedMediaError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc


@app.get("/api/capsules")
async def list_capsules() -> dict[str, Any]:
    capsules = await asyncio.to_thread(_store.list_capsules)
    return {"capsules": [c.to_dict() for c in capsules]}


@app.get("/api/capsules/{capsule_id}")
async def get_capsule(capsule_id: str) -> dict[str, Any]:
    capsule = await asyncio.to_thread(_store.get_capsule, capsule_id)
    if capsule is None:
        raise HTTPException(status_code=404, detail="capsule not found")
    return capsule.to_dict()

# ---------------------------------------------------------------------------
# Health + stub endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "memory": False, "auth_required": False}


@app.get("/api/networks")
def networks_stub() -> None:
    raise HTTPException(
        status_code=503,
        detail="memory networks require: doppler run -- python -m cli serve",
    )

# ---------------------------------------------------------------------------
# Serve the new UI at /
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    target = _INDEX_HTML if _INDEX_HTML.exists() else _TESTER_HTML
    return FileResponse(target)
