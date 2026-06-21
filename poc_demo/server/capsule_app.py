"""Standalone app exposing ONLY the capsule write-path — for local visual testing.

The full ``app.py`` boots embedded Hindsight at startup (slow, needs Doppler +
OpenRouter). The capsule endpoints don't need any of that, so this thin app
re-uses the very same route functions without the Hindsight lifespan. It also
serves stored media back, so you can click a capsule's photo in the browser.

Run it (no Doppler needed):

    .venv/bin/python -m uvicorn poc_demo.server.capsule_app:app --reload --port 8000

Then open http://localhost:8000/docs — interactive Swagger UI where you can fill
in a place, attach a real photo, and hit Execute.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from poc_demo.server import app as full
from poc_demo.server.capsules import DEFAULT_MEDIA_ROOT

_TESTER_PAGE = Path(__file__).parent / "static" / "capsule_tester.html"

app = FastAPI(title="Recall — Capsule API (standalone)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Re-use the exact handlers from the full app — single source of truth.
app.post("/api/capsules", status_code=201)(full.create_capsule)
app.get("/api/capsules")(full.list_capsules)
app.get("/api/capsules/{capsule_id}")(full.get_capsule)

# Serve saved binaries so a capsule's media is viewable at /media/<file_path>.
DEFAULT_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(DEFAULT_MEDIA_ROOT)), name="media")


@app.get("/")
def tester() -> FileResponse:
    """Serve the throwaway capsule-tester UI at the root URL."""
    return FileResponse(_TESTER_PAGE)
