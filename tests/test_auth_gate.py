"""Tests for the local-first passcode gate on the demo API.

When a passcode is configured, protected paths (/api/* except health, and
/media/*) require a matching X-Recall-Token header (or ?t= for media). With no
passcode configured the app is open (laptop-only local dev).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from poc_demo.server import app as app_module
from storage.store import CapsuleStore


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "_store", CapsuleStore(tmp_path / "recall.db"))
    monkeypatch.setattr(app_module, "MEDIA_ROOT", tmp_path / "media")


def test_no_token_app_is_open(isolated: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "RECALL_TOKEN", None)
    client = TestClient(app_module.app)
    assert client.get("/api/capsules").status_code == 200
    assert client.get("/api/health").json()["auth_required"] is False


def test_token_required_rejects_without_header(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "RECALL_TOKEN", "s3cret")
    client = TestClient(app_module.app)
    assert client.get("/api/capsules").status_code == 401
    assert client.get("/api/capsules", headers={"X-Recall-Token": "wrong"}).status_code == 401


def test_token_required_accepts_with_header(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "RECALL_TOKEN", "s3cret")
    client = TestClient(app_module.app)
    assert client.get("/api/capsules", headers={"X-Recall-Token": "s3cret"}).status_code == 200


def test_health_always_open_and_reports_auth(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "RECALL_TOKEN", "s3cret")
    client = TestClient(app_module.app)
    h = client.get("/api/health")  # no header
    assert h.status_code == 200
    assert h.json()["auth_required"] is True


def test_media_accepts_query_param_token(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # <img>/<video> can't send headers, so media accepts the token as ?t=.
    monkeypatch.setattr(app_module, "RECALL_TOKEN", "s3cret")
    client = TestClient(app_module.app)
    # a missing file still proves the gate ran: 401 without token, 404 with it.
    assert client.get("/media/nope.jpg").status_code == 401
    assert client.get("/media/nope.jpg?t=s3cret").status_code == 404
