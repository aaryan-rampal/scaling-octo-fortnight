"""Tests that Claude LLM-chat messages reach the unified events table.

The Claude adapter emits the canonical :class:`~recall.schema.Event` (not a
separate ChatEvent type) and persists through ``adaptors._persist.persist_events``
into the single events table, exactly like iMessage and Spotify.
"""

from __future__ import annotations

from datetime import UTC

from adaptors._persist import persist_events
from adaptors.llm_chats import to_chat_events
from models.llm_export import ClaudeConversation
from recall.schema import Event
from recall.store import CapsuleStore

_CONV = {
    "uuid": "conv-1",
    "name": "Planning",
    "created_at": "2024-02-01T10:00:00Z",
    "chat_messages": [
        {
            "uuid": "m1",
            "sender": "human",
            "text": "What should I cook?",
            "content": [{"type": "text", "text": "What should I cook?"}],
            "created_at": "2024-02-01T10:00:00Z",
            "parent_message_uuid": None,
        },
        {
            "uuid": "m2",
            "sender": "assistant",
            "text": "How about pasta?",
            "content": [{"type": "text", "text": "How about pasta?"}],
            "created_at": "2024-02-01T10:00:05Z",
            "parent_message_uuid": "m1",
        },
    ],
}


def _conversation() -> ClaudeConversation:
    return ClaudeConversation.model_validate(_CONV)


def test_to_chat_events_returns_canonical_events() -> None:
    events = to_chat_events(_conversation())
    assert len(events) == 2
    assert all(isinstance(e, Event) for e in events)
    assert all(e.source == "claude" for e in events)
    assert events[0].author_role == "self"
    assert events[1].author_role == "other"
    assert events[0].thread_id == "conv-1"
    assert events[0].content == "What should I cook?"
    # no source-specific extras for chat: additional_data stays empty.
    assert events[0].additional_data == {}


def test_llm_chats_persist_into_unified_events_table(tmp_path) -> None:
    db = tmp_path / "recall.db"
    events = to_chat_events(_conversation())
    n = persist_events(events, db_path=db)
    assert n == 2
    store = CapsuleStore(db)
    assert len(store.list_events(source="claude")) == 2
    assert store.verify_event(events[0].id) is True
