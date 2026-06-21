"""Tests for the iMessage model + adapter (the refactored adapter/model layer).

The end-to-end chat.db reading is already exercised by ``test_ingest.py`` through
the back-compat shim; these tests target the new typed seam: the
:class:`~models.imessage.IMessageRecord` value object and its projection onto a
canonical :class:`~recall.schema.Event`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from adaptors.imessage import APPLE_EPOCH_OFFSET, records_to_events
from models.imessage import IMessageRecord

_TS = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def _record(**overrides: object) -> IMessageRecord:
    base: dict[str, object] = {
        "rowid": 1,
        "thread_id": "+15551234567",
        "t_utc": _TS,
        "content": "yo",
        "is_from_me": False,
        "reply_to_guid": None,
    }
    base.update(overrides)
    return IMessageRecord(**base)  # type: ignore[arg-type]


def test_author_role_and_raw_ref() -> None:
    assert _record(is_from_me=False).author_role == "other"
    assert _record(is_from_me=True).author_role == "self"
    assert _record(rowid=42).raw_ref == "chat.db#42"


def test_to_event_lands_on_canonical_event() -> None:
    event = _record(reply_to_guid="msg-7").to_event()
    assert event.source == "imessage"
    assert event.author_role == "other"
    assert event.content == "yo"
    assert event.thread_id == "+15551234567"
    assert event.reply_to == "msg-7"
    assert event.raw_ref == "chat.db#1"


def test_event_id_matches_legacy_formula() -> None:
    # The id must equal the legacy recall.ingest derivation so re-ingest stays
    # idempotent and already-stored events keep matching across the refactor.
    apple_ns = int((_TS.timestamp() - APPLE_EPOCH_OFFSET) * 1e9)
    legacy = hashlib.sha256(f"+15551234567|{apple_ns}|0|yo".encode()).hexdigest()[:16]
    assert _record().to_event().id == legacy


def test_event_id_is_deterministic_and_unique() -> None:
    assert _record().to_event().id == _record().to_event().id
    assert _record(content="different").to_event().id != _record().to_event().id


def test_records_to_events_projects_all() -> None:
    events = records_to_events([_record(rowid=1), _record(rowid=2, content="hi")])
    assert [e.raw_ref for e in events] == ["chat.db#1", "chat.db#2"]
    assert all(e.source == "imessage" for e in events)
