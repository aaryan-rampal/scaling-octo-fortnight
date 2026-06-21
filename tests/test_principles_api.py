"""Endpoint tests for the principle trace-back + explain routes.

Mirrors test_capsule_api: TestClient against the real router without entering
the lifespan (so no Hindsight boot), a fixture SQLite DB in tmp_path, and a fake
explainer so no OpenRouter key is needed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from poc_demo.server import app as app_module  # noqa: E402
from storage.trace import PrincipleTrace  # noqa: E402

_SCHEMA = """
CREATE TABLE principles (id TEXT PRIMARY KEY, text TEXT, confidence REAL);
CREATE TABLE memories (
    memory_id TEXT PRIMARY KEY, text TEXT, source TEXT, occurred_start TEXT
);
CREATE TABLE events (
    id TEXT PRIMARY KEY, t_utc TEXT, author_role TEXT, content TEXT,
    raw_ref TEXT, source TEXT
);
CREATE TABLE principle_memories (principle_id TEXT, memory_id TEXT);
CREATE TABLE memory_events (memory_id TEXT, event_id TEXT);
"""


class _FakeExplainer:
    """Stand-in for LLMWhyExplainer; returns canned text, no network or key."""

    def explain(self, trace: PrincipleTrace) -> str:
        return f"Inferred from {len(trace.memories)} memories."


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO principles VALUES (?,?,?)", ("P1", "You decide deliberately.", 0.7))
    conn.execute(
        "INSERT INTO memories VALUES (?,?,?,?)",
        ("M1", "The user weighed a decision model.", "claude", "2025-01-02"),
    )
    conn.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?)",
        ("E1", "2025-01-02T10:00:00Z", "self", "Let me model this.", "claude:c1#1", "claude"),
    )
    conn.execute("INSERT INTO principle_memories VALUES (?,?)", ("P1", "M1"))
    conn.execute("INSERT INTO memory_events VALUES (?,?)", ("M1", "E1"))
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "trace.db"
    _build_db(db)
    monkeypatch.setattr(app_module, "TRACE_DB", str(db))
    monkeypatch.setattr(app_module, "LLMWhyExplainer", _FakeExplainer)
    return TestClient(app_module.app, raise_server_exceptions=True)


def test_list_principles(client: TestClient) -> None:
    resp = client.get("/api/principles")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["principles"][0]["id"] == "P1"
    assert body["principles"][0]["confidence"] == 0.7


def test_principle_why_returns_trace_and_explanation(client: TestClient) -> None:
    resp = client.get("/api/principles/P1/why")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["principle"]["id"] == "P1"
    assert body["memories"][0]["events"][0]["raw_ref"] == "claude:c1#1"
    assert body["why"] == "Inferred from 1 memories."


def test_principle_why_unknown_id_is_404(client: TestClient) -> None:
    resp = client.get("/api/principles/nope/why")
    assert resp.status_code == 404


def test_trace_db_missing_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "TRACE_DB", str(tmp_path / "absent.db"))
    c = TestClient(app_module.app, raise_server_exceptions=True)
    assert c.get("/api/principles").status_code == 503
    assert c.get("/api/principles/P1/why").status_code == 503
