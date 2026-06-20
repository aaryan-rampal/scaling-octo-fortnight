"""Read-only ingest of iMessage history from ``~/Library/Messages/chat.db``.

The database is opened in SQLite read-only URI mode and never written to. Most
modern messages store their text in the ``attributedBody`` typedstream BLOB
rather than the ``text`` column, so this module ships a best-effort decoder for
that format. Rows whose body cannot be decoded are skipped rather than crashing
the run.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import struct
from datetime import UTC, date, datetime

from recall.schema import Event, write_events_jsonl

# Apple's Core Data epoch (2001-01-01 UTC) as seconds past the Unix epoch.
APPLE_EPOCH_OFFSET = 978_307_200

# typedstream marker that precedes an NSString payload: the byte sequence is
# ``\x84\x01`` (a class-version reference) followed by ``+`` (0x2b), the type
# encoding for an Objective-C ``char *``. The following byte(s) encode length.
_NSSTRING_ANCHOR = b"\x84\x01+"

DEFAULT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")
DEFAULT_OUTPUT = "data/events.jsonl"


def apple_ns_to_utc(apple_ns: int) -> datetime:
    """Convert an Apple-epoch nanosecond timestamp to a UTC datetime.

    Args:
        apple_ns: Nanoseconds since 2001-01-01 UTC, as stored in ``message.date``.

    Returns:
        A timezone-aware UTC datetime.
    """
    unix_seconds = apple_ns / 1e9 + APPLE_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_seconds, tz=UTC)


def decode_attributed_body(blob: bytes | None) -> str | None:
    """Extract the plain string from an ``attributedBody`` typedstream BLOB.

    The decoder anchors on the NSString type marker and reads the length-prefixed
    UTF-8 payload that follows. Length is encoded as a single byte, or as ``0x81``
    plus a little-endian ``uint16``, or ``0x82`` plus a little-endian ``uint32``.

    Args:
        blob: The raw ``attributedBody`` bytes, or ``None``.

    Returns:
        The decoded message text, or ``None`` if the blob is empty or the marker
        cannot be located.
    """
    if not blob:
        return None
    anchor = blob.find(_NSSTRING_ANCHOR)
    if anchor < 0:
        return None
    pos = anchor + len(_NSSTRING_ANCHOR)
    if pos >= len(blob):
        return None
    first = blob[pos]
    if first == 0x81:
        length = struct.unpack_from("<H", blob, pos + 1)[0]
        start = pos + 3
    elif first == 0x82:
        length = struct.unpack_from("<I", blob, pos + 1)[0]
        start = pos + 4
    else:
        length = first
        start = pos + 1
    payload = blob[start : start + length]
    if not payload:
        return None
    return payload.decode("utf-8", "replace")


def connect_readonly(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open ``chat.db`` in read-only mode.

    Args:
        db_path: Filesystem path to the SQLite database.

    Returns:
        A read-only SQLite connection.
    """
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def top_threads(conn: sqlite3.Connection, n: int) -> list[tuple[str, str]]:
    """Rank conversations by message volume.

    Args:
        conn: Open connection to ``chat.db``.
        n: Number of threads to return.

    Returns:
        Up to ``n`` ``(chat_identifier, display_handle)`` tuples, busiest first.
        ``display_handle`` falls back to ``chat_identifier`` when the chat has no
        display name.
    """
    rows = conn.execute(
        """
        SELECT c.chat_identifier, c.display_name, COUNT(*) AS cnt
        FROM chat c
        JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
        GROUP BY c.ROWID
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    threads: list[tuple[str, str]] = []
    for chat_identifier, display_name, _cnt in rows:
        handle = display_name or chat_identifier
        threads.append((chat_identifier, handle))
    return threads


def _event_id(thread_id: str, apple_ns: int, is_from_me: int, content: str) -> str:
    """Build a stable event id from the fields that uniquely place a message."""
    key = f"{thread_id}|{apple_ns}|{is_from_me}|{content}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _rows_for_thread(
    conn: sqlite3.Connection, chat_identifier: str, since_ns: int | None
) -> list[tuple]:
    """Fetch raw message rows for a single thread, optionally bounded by time."""
    query = """
        SELECT m.ROWID, m.date, m.text, m.attributedBody, m.is_from_me,
               m.reply_to_guid
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        JOIN chat c ON c.ROWID = cmj.chat_id
        WHERE c.chat_identifier = ?
    """
    params: list[object] = [chat_identifier]
    if since_ns is not None:
        query += " AND m.date >= ?"
        params.append(since_ns)
    query += " ORDER BY m.date ASC"
    return conn.execute(query, params).fetchall()


def _build_event(row: tuple, thread_id: str) -> Event | None:
    """Convert a raw message row into an :class:`Event`, or ``None`` to skip it."""
    rowid, apple_ns, text, attributed_body, is_from_me, reply_to_guid = row
    content = text if text is not None else decode_attributed_body(attributed_body)
    if not content or not content.strip():
        return None
    return Event(
        id=_event_id(thread_id, apple_ns, is_from_me, content),
        t_utc=apple_ns_to_utc(apple_ns),
        author_role="self" if is_from_me else "other",
        content=content,
        thread_id=thread_id,
        reply_to=reply_to_guid,
        raw_ref=f"chat.db#{rowid}",
        source="imessage",
    )


def ingest(
    top_n: int,
    since: date | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> list[Event]:
    """Ingest events from the busiest threads in ``chat.db``.

    Args:
        top_n: Number of top threads (by volume) to ingest.
        since: Optional lower bound; only messages on or after this date are kept.
        db_path: Path to the SQLite database.

    Returns:
        Events from the selected threads, ordered by thread then timestamp. Rows
        whose body cannot be decoded are silently skipped.
    """
    since_ns: int | None = None
    if since is not None:
        midnight = datetime(since.year, since.month, since.day, tzinfo=UTC)
        unix_seconds = midnight.timestamp() - APPLE_EPOCH_OFFSET
        since_ns = int(unix_seconds * 1e9)

    conn = connect_readonly(db_path)
    try:
        events: list[Event] = []
        for chat_identifier, _handle in top_threads(conn, top_n):
            for row in _rows_for_thread(conn, chat_identifier, since_ns):
                event = _build_event(row, chat_identifier)
                if event is not None:
                    events.append(event)
        return events
    finally:
        conn.close()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the ingest entry point."""
    parser = argparse.ArgumentParser(description="Ingest iMessage history to JSONL.")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top threads.")
    parser.add_argument("--since", type=str, default=None, help="Lower bound YYYY-MM-DD.")
    parser.add_argument("--out", type=str, default=DEFAULT_OUTPUT, help="Output JSONL path.")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to chat.db.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: ingest events and write them to a JSONL file."""
    args = _parse_args(argv)
    since = date.fromisoformat(args.since) if args.since else None
    events = ingest(args.top_n, since=since, db_path=args.db)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    written = write_events_jsonl(events, args.out)
    print(f"Wrote {written} events to {args.out}")


if __name__ == "__main__":
    main()
