"""Offline tests for the "why" agent (pipeline.explain).

A ``FakeExplainer`` stands in for the LLM, so these run with no network and no
key. They prove (1) the evidence block renders real facts, and (2) the
trace → dict-with-``why`` assembly is correct, including not-found.
"""

from __future__ import annotations

import sqlite3

from pipeline.explain import explain_principle, render_evidence
from storage.trace import PrincipleTrace, trace_principle

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


def _fixture_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO principles VALUES (?,?,?)", ("P1", "You decide deliberately.", 0.7))
    conn.execute(
        "INSERT INTO memories VALUES (?,?,?,?)",
        ("M1", "The user weighed a decision model.", "claude", "2025-01-02"),
    )
    conn.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?)",
        (
            "E1", "2025-01-02T10:00:00Z", "self",
            "Let me model the expected value.", "claude:c1#1", "claude",
        ),
    )
    conn.execute("INSERT INTO principle_memories VALUES (?,?)", ("P1", "M1"))
    conn.execute("INSERT INTO memory_events VALUES (?,?)", ("M1", "E1"))
    conn.commit()
    return conn


class FakeExplainer:
    """Records the trace it was handed and returns a canned explanation."""

    def __init__(self) -> None:
        self.seen: PrincipleTrace | None = None

    def explain(self, trace: PrincipleTrace) -> str:
        self.seen = trace
        return "This showed up because you kept reasoning things through."


def test_render_evidence_contains_grounding_facts() -> None:
    conn = _fixture_conn()
    trace = trace_principle(conn, "P1")
    block = render_evidence(trace)

    assert "You decide deliberately." in block
    assert "The user weighed a decision model." in block
    assert "Let me model the expected value." in block
    assert "claude:c1#1" in block  # the raw_ref must reach the prompt


def test_render_evidence_handles_empty_memories() -> None:
    empty = PrincipleTrace(principle_id="P0", text="Lonely principle.", confidence=0.4, memories=[])
    block = render_evidence(empty)
    assert "empty" in block.lower()


def test_explain_principle_assembles_result() -> None:
    conn = _fixture_conn()
    fake = FakeExplainer()
    result = explain_principle(conn, "P1", fake)

    assert result is not None
    assert result["principle"]["id"] == "P1"
    assert result["why"] == "This showed up because you kept reasoning things through."
    assert len(result["memories"]) == 1
    assert fake.seen is not None and fake.seen.principle_id == "P1"


def test_explain_principle_unknown_returns_none() -> None:
    conn = _fixture_conn()
    assert explain_principle(conn, "nope", FakeExplainer()) is None
