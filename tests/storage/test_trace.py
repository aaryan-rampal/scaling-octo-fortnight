"""Offline tests for the principle trace-back (storage.trace).

Builds a tiny in-memory SQLite DB matching the provenance schema (no external
``.db`` file, no network), then asserts the ladder query reassembles the nested
principle → memories → events shape correctly, including the thin-evidence,
duplicate-row, not-found, and read-only edge cases.
"""

from __future__ import annotations

import sqlite3

import pytest

from storage.trace import PrincipleTrace, open_db, to_dict, trace_principle

# Minimal slice of data/derek_handoff/SCHEMA.md — only the columns trace.py reads.
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

_MEMORIES = [
    ("M1", "The user weighed a vaccine decision model.", "claude", "2025-01-02"),
    ("M2", "The user planned research directions.", "claude", "2025-02-05"),
]
_EVENTS = [
    (
        "E1", "2025-01-02T10:00:00Z", "self",
        "Let me model the expected value.", "claude:c1#1", "claude",
    ),
    (
        "E2", "2025-01-02T10:05:00Z", "self",
        "Decision theory says hold.", "claude:c1#2", "claude",
    ),
]


def _seed(conn: sqlite3.Connection) -> None:
    """Seed one principle: 2 memories, M1 with 2 events, M2 with none."""
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO principles VALUES (?,?,?)",
        ("P1", "You make deliberate, informed decisions.", 0.7),
    )
    conn.executemany("INSERT INTO memories VALUES (?,?,?,?)", _MEMORIES)
    conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)", _EVENTS)
    conn.executemany(
        "INSERT INTO principle_memories VALUES (?,?)",
        [("P1", "M1"), ("P1", "M2")],
    )
    conn.executemany(
        "INSERT INTO memory_events VALUES (?,?)",
        [("M1", "E1"), ("M1", "E2")],  # M2 deliberately has no events
    )
    conn.commit()


def _fixture_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    return conn


def test_trace_principle_assembles_nested_shape() -> None:
    conn = _fixture_conn()
    trace = trace_principle(conn, "P1")

    assert isinstance(trace, PrincipleTrace)
    assert trace.principle_id == "P1"
    assert trace.confidence == 0.7
    assert len(trace.memories) == 2

    by_id = {m.memory_id: m for m in trace.memories}
    assert [e.id for e in by_id["M1"].events] == ["E1", "E2"]  # ordered by t_utc
    assert by_id["M1"].events[0].content == "Let me model the expected value."
    assert by_id["M1"].events[0].raw_ref == "claude:c1#1"


def test_thin_memory_keeps_empty_event_list() -> None:
    conn = _fixture_conn()
    trace = trace_principle(conn, "P1")
    by_id = {m.memory_id: m for m in trace.memories}

    # M2 has no linked events — it must still appear, with an empty list.
    assert "M2" in by_id
    assert by_id["M2"].events == []


def test_duplicate_join_rows_do_not_duplicate_events() -> None:
    conn = _fixture_conn()
    # A duplicate link row would multiply through the JOIN; trace must dedupe.
    conn.execute("INSERT INTO principle_memories VALUES (?,?)", ("P1", "M1"))
    conn.execute("INSERT INTO memory_events VALUES (?,?)", ("M1", "E1"))
    conn.commit()

    trace = trace_principle(conn, "P1")
    by_id = {m.memory_id: m for m in trace.memories}
    assert len(trace.memories) == 2  # M1 still appears once
    assert [e.id for e in by_id["M1"].events] == ["E1", "E2"]  # no E1 twice


def test_null_confidence_does_not_crash() -> None:
    conn = _fixture_conn()
    conn.execute("INSERT INTO principles VALUES (?,?,?)", ("P_NULL", "Conf is null.", None))
    conn.execute("INSERT INTO principle_memories VALUES (?,?)", ("P_NULL", "M1"))
    conn.execute("INSERT INTO memory_events VALUES (?,?)", ("M1", "E1"))
    conn.commit()

    trace = trace_principle(conn, "P_NULL")
    assert trace is not None
    assert trace.confidence == 0.0


def test_unknown_principle_returns_none() -> None:
    conn = _fixture_conn()
    assert trace_principle(conn, "does-not-exist") is None


def test_to_dict_is_json_shaped() -> None:
    conn = _fixture_conn()
    trace = trace_principle(conn, "P1")
    d = to_dict(trace)

    assert d["principle"]["id"] == "P1"
    assert len(d["memories"]) == 2
    m1 = next(m for m in d["memories"] if m["memory_id"] == "M1")
    assert len(m1["events"]) == 2
    assert m1["events"][0]["raw_ref"] == "claude:c1#1"


def test_open_db_is_read_only(tmp_path) -> None:
    db = tmp_path / "real.db"
    seed = sqlite3.connect(db)
    _seed(seed)
    seed.close()

    conn = open_db(db)
    try:
        assert trace_principle(conn, "P1") is not None  # reads work
        with pytest.raises(sqlite3.OperationalError):  # writes are refused
            conn.execute("INSERT INTO principles VALUES ('X','x',0.1)")
            conn.commit()
    finally:
        conn.close()


def test_open_db_missing_file_raises(tmp_path) -> None:
    # Must NOT silently create an empty DB on a wrong path.
    with pytest.raises(sqlite3.OperationalError):
        open_db(tmp_path / "nope.db")
