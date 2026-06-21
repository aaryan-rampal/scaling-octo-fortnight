"""Tests for the iMessage ingest layer against a synthetic fixture database."""

from __future__ import annotations

import sqlite3
import struct
from datetime import UTC, date, datetime
from pathlib import Path

from adapters.imessage import (
    APPLE_EPOCH_OFFSET,
    apple_ns_to_utc,
    decode_attributed_body,
    ingest,
    top_threads,
)

# A known message body whose only copy lives in an attributedBody BLOB.
_ATTR_TEXT = "hello from attributedBody"


def _make_attributed_body(text: str) -> bytes:
    """Build a minimal typedstream BLOB the decoder can parse.

    Mirrors the real ``attributedBody`` layout closely enough for the test: a
    typedstream header, the NSString class chain, the ``\\x84\\x01+`` anchor, a
    short length byte, and the UTF-8 payload.
    """
    payload = text.encode("utf-8")
    header = b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x08NSString\x01\x94"
    return header + b"\x84\x01+" + bytes([len(payload)]) + payload + b"\x86\x84\x02iI"


def _make_long_attributed_body(text: str) -> bytes:
    """Build a typedstream BLOB using the 0x81 long-length encoding."""
    payload = text.encode("utf-8")
    header = b"\x04\x0bstreamtyped\x84\x84\x84\x08NSString\x01\x94"
    return header + b"\x84\x01+\x81" + struct.pack("<H", len(payload)) + payload


def _unix_to_apple_ns(dt: datetime) -> int:
    """Convert a UTC datetime to an Apple-epoch nanosecond integer."""
    return int((dt.timestamp() - APPLE_EPOCH_OFFSET) * 1e9)


def _build_fixture_db(path: Path) -> None:
    """Create a tiny chat.db-shaped fixture with two threads of unequal size."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT,
            chat_identifier TEXT,
            display_name TEXT
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT,
            text TEXT,
            attributedBody BLOB,
            handle_id INTEGER,
            is_from_me INTEGER,
            date INTEGER,
            reply_to_guid TEXT
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER,
            message_id INTEGER,
            message_date INTEGER
        );
        """
    )
    conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, '+15551234567')")
    conn.execute(
        "INSERT INTO chat (ROWID, guid, chat_identifier, display_name) "
        "VALUES (1, 'g-big', '+15551234567', NULL)"
    )
    conn.execute(
        "INSERT INTO chat (ROWID, guid, chat_identifier, display_name) "
        "VALUES (2, 'g-small', 'group-xyz', 'Study Group')"
    )

    base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    rows = [
        # (rowid, text, attributedBody, is_from_me, dt, reply_to, chat_id)
        (1, "yo", None, 0, base, None, 1),
        (2, None, _make_attributed_body(_ATTR_TEXT), 1, base, None, 1),
        (3, "third in big thread", None, 0, base, None, 1),
        (4, "fourth in big thread", None, 1, base, None, 1),
        (5, "only message in small thread", None, 0, base, None, 2),
    ]
    for rowid, text, body, from_me, dt, reply_to, chat_id in rows:
        apple_ns = _unix_to_apple_ns(dt)
        conn.execute(
            "INSERT INTO message "
            "(ROWID, guid, text, attributedBody, is_from_me, date, reply_to_guid) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rowid, f"msg-{rowid}", text, body, from_me, apple_ns, reply_to),
        )
        conn.execute(
            "INSERT INTO chat_message_join (chat_id, message_id, message_date) VALUES (?, ?, ?)",
            (chat_id, rowid, apple_ns),
        )
    conn.commit()
    conn.close()


def test_apple_epoch_conversion_known_value() -> None:
    # 2001-01-01 00:00:00 UTC is exactly 0 nanoseconds in Apple's epoch.
    assert apple_ns_to_utc(0) == datetime(2001, 1, 1, tzinfo=UTC)
    # 2024-01-01 12:00:00 UTC round-trips.
    target = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    apple_ns = int((target.timestamp() - APPLE_EPOCH_OFFSET) * 1e9)
    assert apple_ns_to_utc(apple_ns) == target


def test_attributed_body_short_length() -> None:
    blob = _make_attributed_body(_ATTR_TEXT)
    assert decode_attributed_body(blob) == _ATTR_TEXT


def test_attributed_body_long_length() -> None:
    text = "x" * 300
    blob = _make_long_attributed_body(text)
    assert decode_attributed_body(blob) == text


def test_attributed_body_handles_missing_marker() -> None:
    assert decode_attributed_body(b"no marker here") is None
    assert decode_attributed_body(None) is None
    assert decode_attributed_body(b"") is None


def test_attributed_body_truncated_length_prefix() -> None:
    # Regression (BUG.md #1): a blob that ends right after the 0x81/0x82 length
    # marker must return None, not raise struct.error and kill the whole ingest.
    assert decode_attributed_body(b"\x84\x01+\x81\x05") is None  # 0x81 wants 2 bytes
    assert decode_attributed_body(b"\x84\x01+\x82\x05") is None  # 0x82 wants 4 bytes
    assert decode_attributed_body(b"\x84\x01+\x81") is None  # nothing after marker


def test_top_threads_ranks_by_volume(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    _build_fixture_db(db)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        ranked = top_threads(conn, n=5)
    finally:
        conn.close()
    # Big thread (4 messages) ranks above small thread (1 message).
    assert [ident for ident, _handle in ranked] == ["+15551234567", "group-xyz"]
    # display_name falls back to chat_identifier when null, else uses the name.
    assert ranked[0][1] == "+15551234567"
    assert ranked[1][1] == "Study Group"


def test_ingest_maps_author_role_and_decodes_body(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    _build_fixture_db(db)
    events = ingest(top_n=5, db_path=str(db))

    assert len(events) == 5
    by_content = {e.content: e for e in events}

    # attributedBody fallback produced the decoded text.
    assert _ATTR_TEXT in by_content
    # is_from_me mapping.
    assert by_content["yo"].author_role == "other"
    assert by_content[_ATTR_TEXT].author_role == "self"
    # thread_id is the chat identifier.
    assert by_content["only message in small thread"].thread_id == "group-xyz"
    # raw_ref points back at the source row.
    assert by_content["yo"].raw_ref == "chat.db#1"


def test_ingest_since_filters_old_messages(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    _build_fixture_db(db)
    # All fixture messages are dated 2024-01-01; a later bound excludes them all.
    events = ingest(top_n=5, since=date(2025, 1, 1), db_path=str(db))
    assert events == []
