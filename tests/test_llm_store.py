"""Tests for the LLM-chat store (no network).

These exercise :class:`recall.llm_store.LLMStore`, the sibling table that
persists :class:`ChatEvent` rows produced by the LLM-chat adaptor. The style
mirrors ``tests/test_capsule_store.py``: an in-memory store, hand-built rows for
unit assertions, plus one real-data slice driven by the adaptor to prove the
store works end-to-end on actual export output.
"""

from __future__ import annotations

from datetime import UTC, datetime

from adaptors.llm_chats import ingest_export
from models.chat_event import ChatEvent
from recall.llm_store import LLMStore

_FIXTURE = "tests/fixtures/llm_export"


def _event(
    eid: str,
    *,
    content: str = "hello",
    thread_id: str = "t1",
    reply_to: str | None = None,
    source: str = "claude",
    minute: int = 0,
) -> ChatEvent:
    return ChatEvent(
        id=eid,
        t_utc=datetime(2026, 6, 20, 18, minute, tzinfo=UTC),
        author_role="self",
        content=content,
        thread_id=thread_id,
        reply_to=reply_to,
        raw_ref=f"claude:{thread_id}#{eid}",
        source=source,
    )


def test_roundtrip_preserves_fields() -> None:
    store = LLMStore(":memory:")
    a = _event("a", content="first", reply_to=None, minute=0)
    b = _event("b", content="second", reply_to="a", minute=1)
    assert store.add_llm_messages([a, b]) == 2

    rows = store.list_llm_messages()
    assert [r.id for r in rows] == ["a", "b"]
    first = rows[0]
    assert first.content == "first"
    assert first.reply_to is None
    assert first.source == "claude"
    assert first.t_utc == datetime(2026, 6, 20, 18, 0, tzinfo=UTC)
    assert first.t_utc.tzinfo is not None
    assert rows[1].reply_to == "a"


def test_add_is_idempotent_on_id() -> None:
    store = LLMStore(":memory:")
    events = [_event("a", minute=0), _event("b", minute=1)]

    assert store.add_llm_messages(events) == 2
    # Re-adding the same ids reports a count but must not duplicate rows.
    assert store.add_llm_messages(events) == 2

    rows = store.list_llm_messages()
    assert [r.id for r in rows] == ["a", "b"]
    assert len(rows) == 2


def test_verify_provenance_true_and_unknown_none() -> None:
    store = LLMStore(":memory:")
    store.add_llm_messages([_event("a", content="the night before")])

    assert store.verify_llm_message("a") is True
    assert store.verify_llm_message("missing") is None


def test_verify_recomputes_sha_on_reinsert() -> None:
    store = LLMStore(":memory:")
    store.add_llm_messages([_event("a", content="v1")])
    # Re-inserting the same id with new content recomputes the stored hash,
    # so the provenance check still matches the latest content.
    store.add_llm_messages([_event("a", content="v2")])

    rows = store.list_llm_messages()
    assert len(rows) == 1
    assert rows[0].content == "v2"
    assert store.verify_llm_message("a") is True


def test_filter_by_source_and_thread() -> None:
    store = LLMStore(":memory:")
    store.add_llm_messages(
        [
            _event("a", thread_id="t1", source="claude", minute=0),
            _event("b", thread_id="t2", source="claude", minute=1),
            _event("c", thread_id="t1", source="gpt", minute=2),
        ]
    )

    assert [r.id for r in store.list_llm_messages(source="claude")] == ["a", "b"]
    assert [r.id for r in store.list_llm_messages(thread_id="t1")] == ["a", "c"]
    assert [r.id for r in store.list_llm_messages(source="claude", thread_id="t1")] == ["a"]


def test_real_export_slice_roundtrips_and_is_idempotent() -> None:
    events = ingest_export(_FIXTURE)
    assert events  # fixture is non-empty

    store = LLMStore(":memory:")
    assert store.add_llm_messages(events) == len(events)
    assert len(store.list_llm_messages()) == len(events)

    # Re-ingesting the same export must not grow the table (idempotent on id).
    store.add_llm_messages(events)
    assert len(store.list_llm_messages()) == len(events)
    assert all(r.source == "claude" for r in store.list_llm_messages())
