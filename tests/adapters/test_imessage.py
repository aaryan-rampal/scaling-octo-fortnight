"""Tests for the iMessage model + adapter (the refactored adapter/model layer).

The end-to-end chat.db reading is already exercised by ``test_ingest.py`` through
the back-compat shim; these tests target the new typed seam: the
:class:`~models.imessage.IMessageRecord` value object and its projection onto a
canonical :class:`~core.schema.Event`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from adapters.imessage import (
    APPLE_EPOCH_OFFSET,
    build_contact_map,
    normalize_handle,
    records_to_events,
    resolve_contact_name,
)
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


def test_normalize_handle_phone_email_and_group() -> None:
    # Differently formatted numbers for the same line collapse to one key.
    assert normalize_handle("+16046526819") == normalize_handle("+1 604 652 6819")
    assert normalize_handle("+16046526819") == "6046526819"
    # Email handles lowercase and match exactly; group ids do not resolve.
    assert normalize_handle("Foo@Example.com") == "foo@example.com"
    assert normalize_handle("chat373748529303500053") is None
    assert normalize_handle("") is None


def _make_contacts_db(path: Path) -> None:
    """Build a tiny fixture mirroring the macOS Contacts schema we query."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE ZABCDRECORD (
            Z_PK INTEGER PRIMARY KEY,
            ZFIRSTNAME VARCHAR, ZLASTNAME VARCHAR, ZNICKNAME VARCHAR
        );
        CREATE TABLE ZABCDPHONENUMBER (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZFULLNUMBER VARCHAR
        );
        CREATE TABLE ZABCDEMAILADDRESS (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZADDRESS VARCHAR
        );
        INSERT INTO ZABCDRECORD VALUES
            (1, 'Justin', 'Cho', NULL),
            (2, NULL, NULL, 'Bestie'),
            (3, 'Namira', NULL, NULL);
        INSERT INTO ZABCDPHONENUMBER VALUES
            (10, 1, '+1 (778) 865-4932'),
            (11, 2, '604 379 9064');
        INSERT INTO ZABCDEMAILADDRESS VALUES
            (20, 3, 'Namira12345@Gmail.com');
        """
    )
    conn.commit()
    conn.close()


def test_build_contact_map_phone_email_and_nickname(tmp_path: Path) -> None:
    src = tmp_path / "Sources" / "abc"
    src.mkdir(parents=True)
    _make_contacts_db(src / "AddressBook-v22.abcddb")
    glob = str(tmp_path / "Sources" / "*" / "AddressBook-v22.abcddb")

    contact_map = build_contact_map(glob)

    # Phone with first+last, phone with nickname-only, lowercased email.
    assert contact_map["7788654932"] == "Justin Cho"
    assert contact_map["6043799064"] == "Bestie"
    assert contact_map["namira12345@gmail.com"] == "Namira"


def test_resolve_contact_name_unknown_handle_is_none(tmp_path: Path) -> None:
    src = tmp_path / "Sources" / "abc"
    src.mkdir(parents=True)
    _make_contacts_db(src / "AddressBook-v22.abcddb")
    glob = str(tmp_path / "Sources" / "*" / "AddressBook-v22.abcddb")
    contact_map = build_contact_map(glob)

    assert resolve_contact_name("+17788654932", contact_map) == "Justin Cho"
    assert resolve_contact_name("+19998887777", contact_map) is None
    assert resolve_contact_name("chat999", contact_map) is None


def test_build_contact_map_missing_db_is_empty() -> None:
    assert build_contact_map("/nonexistent/path/*/AddressBook-v22.abcddb") == {}


def test_records_to_events_injects_contact_name() -> None:
    contact_map = {"7788654932": "Justin Cho"}
    known = _record(thread_id="+17788654932")
    unknown = _record(thread_id="+19998887777")

    events = records_to_events([known, unknown], contact_map)

    assert events[0].additional_data["contact_name"] == "Justin Cho"
    assert "contact_name" not in events[1].additional_data


def test_records_to_events_no_map_leaves_data_untouched() -> None:
    events = records_to_events([_record(thread_id="+17788654932")])
    assert events[0].additional_data == {}
