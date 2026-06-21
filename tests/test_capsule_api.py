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
from recall.store import CapsuleStore  # noqa: E402


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
