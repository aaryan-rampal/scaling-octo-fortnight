"""Tests for the shared ChatEvent base model (models.chat_event).

ChatEvent is the Pydantic v2 mirror of recall.schema.Event: the canonical
conversational-message shape that source adaptors (iMessage, LLM chats) produce.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from models.chat_event import ChatEvent


def _fields() -> dict[str, object]:
    return {
        "id": "abc123",
        "t_utc": datetime(2025, 11, 23, 17, 43, 52, tzinfo=UTC),
        "author_role": "self",
        "content": "hello world",
        "thread_id": "thread-1",
        "reply_to": None,
        "raw_ref": "claude:thread-1#msg-1",
        "source": "claude",
    }


def test_construct_with_all_fields() -> None:
    ev = ChatEvent.model_validate(_fields())
    assert ev.id == "abc123"
    assert ev.author_role == "self"
    assert ev.content == "hello world"
    assert ev.thread_id == "thread-1"
    assert ev.reply_to is None
    assert ev.raw_ref == "claude:thread-1#msg-1"
    assert ev.source == "claude"


def test_t_utc_is_tz_aware() -> None:
    ev = ChatEvent.model_validate(_fields())
    assert ev.t_utc.tzinfo is not None
    assert ev.t_utc.utcoffset() == UTC.utcoffset(None)


def test_reply_to_accepts_a_value() -> None:
    fields = _fields()
    fields["reply_to"] = "parent-id"
    ev = ChatEvent.model_validate(fields)
    assert ev.reply_to == "parent-id"


def test_missing_required_field_fails() -> None:
    fields = _fields()
    del fields["content"]
    with pytest.raises(ValidationError):
        ChatEvent.model_validate(fields)
