"""Endpoint tests for the capsule write-path.

Uses FastAPI's TestClient against the real router but with a temp store/media
root, so no Hindsight/OpenRouter is needed. The lifespan (which boots embedded
Hindsight) is intentionally *not* entered — TestClient is used as a plain WSGI
caller via ``app`` without the startup context, and these endpoints don't touch
``_state``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from poc_demo.server import app as app_module  # noqa: E402
from storage.store import CapsuleStore  # noqa: E402


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A TestClient whose store + media root are isolated to tmp_path."""
    monkeypatch.setattr(app_module, "_store", CapsuleStore(tmp_path / "recall.db"))
    monkeypatch.setattr(app_module, "MEDIA_ROOT", tmp_path / "media")
    # Avoid entering lifespan (which boots Hindsight) by not using `with`.
    return TestClient(app_module.app, raise_server_exceptions=True)


def test_create_capsule_with_photo(client: TestClient) -> None:
    resp = client.post(
        "/api/capsules",
        data={"place_name": "Moffitt Library", "lat": "37.872", "lng": "-122.260"},
        files={"media": ("photo.jpg", b"\xff\xd8image", "image/jpeg")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["place_name"] == "Moffitt Library"
    assert body["lat"] == 37.872
    assert len(body["media"]) == 1
    assert body["media"][0]["kind"] == "photo"

    # round-trips through GET
    got = client.get(f"/api/capsules/{body['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]

    listed = client.get("/api/capsules").json()["capsules"]
    assert any(c["id"] == body["id"] for c in listed)


def test_create_capsule_requires_place_name(client: TestClient) -> None:
    resp = client.post("/api/capsules", data={"place_name": "   "})
    assert resp.status_code == 422


def test_create_capsule_rejects_unsupported_media(client: TestClient) -> None:
    resp = client.post(
        "/api/capsules",
        data={"place_name": "X"},
        files={"media": ("doc.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 415


def test_get_missing_capsule_404(client: TestClient) -> None:
    assert client.get("/api/capsules/nope").status_code == 404


def test_create_capsule_no_media(client: TestClient) -> None:
    resp = client.post("/api/capsules", data={"place_name": "Empty"})
    assert resp.status_code == 201
    assert resp.json()["media"] == []


def test_create_capsule_persists_canonical_event(client: TestClient) -> None:
    # The honest write path: a capsule also lands in the unified events table as
    # a canonical Event (source="capsule"), alongside the passive sources.
    resp = client.post(
        "/api/capsules",
        data={"place_name": "Greek Theatre", "lat": "37.873", "lng": "-122.254"},
        files={"media": ("photo.jpg", b"\xff\xd8image", "image/jpeg")},
    )
    assert resp.status_code == 201
    capsule_id = resp.json()["id"]

    events = app_module._store.list_events(source="capsule")
    assert len(events) == 1
    ev = events[0]
    assert ev.id == capsule_id
    assert ev.raw_ref == f"capsule#{capsule_id}"
    assert ev.additional_data["place_name"] == "Greek Theatre"
    assert app_module._store.verify_event(ev.id) is True  # provenance intact


def test_capsule_note_becomes_event_content(client: TestClient) -> None:
    # The journal note (a text/plain upload) is surfaced as the event content.
    resp = client.post(
        "/api/capsules",
        data={"place_name": "Lake"},
        files={"media": ("note.txt", b"a calm evening", "text/plain")},
    )
    assert resp.status_code == 201
    events = app_module._store.list_events(source="capsule")
    assert events[-1].content == "a calm evening"
