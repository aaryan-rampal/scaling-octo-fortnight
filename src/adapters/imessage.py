"""Adapter for the macOS Messages database (``~/Library/Messages/chat.db``).

The canonical home for iMessage ingest, paralleling :mod:`adapters.spotify`. It
opens ``chat.db`` **read-only** (and never writes to it), decodes message bodies
— most live in an ``attributedBody`` typedstream BLOB rather than the ``text``
column — validates each row into a :class:`~models.imessage.IMessageRecord`, and
projects the records onto canonical :class:`~core.schema.Event` rows via
:meth:`IMessageRecord.to_event`.

This keeps iMessage on the **same provenance path as every other source**: the
emitted events go through ``storage.store.CapsuleStore.add_events`` (durable
``events`` table + ``content_sha`` integrity hash), then
``pipeline.episodes.build_episodes`` windowing, then Hindsight ``retain`` — no
source-specific handling downstream.

This is the single home for iMessage ingest; the CLI and tests import directly
from here.

CLI::

    python -m adapters.imessage --top-n 5 [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import struct
from datetime import UTC, date, datetime

from core.schema import Event, write_events_jsonl
from models.imessage import IMessageRecord
from storage.persist import persist_events

#: Apple's Core Data epoch (2001-01-01 UTC) as seconds past the Unix epoch.
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
        # 0x81 promises a 2-byte length; bail if the blob is truncated before it.
        if pos + 3 > len(blob):
            return None
        length = struct.unpack_from("<H", blob, pos + 1)[0]
        start = pos + 3
    elif first == 0x82:
        # 0x82 promises a 4-byte length; bail if the blob is truncated before it.
        if pos + 5 > len(blob):
            return None
        length = struct.unpack_from("<I", blob, pos + 1)[0]
        start = pos + 5
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


def _build_record(row: tuple, thread_id: str) -> IMessageRecord | None:
    """Validate a raw message row into an :class:`IMessageRecord`, or skip it.

    Returns ``None`` when the row has no decodable, non-blank body — such rows
    (attachments, tapbacks, undecodable BLOBs) carry no text to retain.
    """
    rowid, apple_ns, text, attributed_body, is_from_me, reply_to_guid = row
    content = text if text is not None else decode_attributed_body(attributed_body)
    if not content or not content.strip():
        return None
    return IMessageRecord(
        rowid=rowid,
        thread_id=thread_id,
        t_utc=apple_ns_to_utc(apple_ns),
        content=content,
        is_from_me=bool(is_from_me),
        reply_to_guid=reply_to_guid,
    )


def read_records(
    top_n: int,
    since: date | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> list[IMessageRecord]:
    """Read and decode messages from the busiest threads in ``chat.db``.

    Args:
        top_n: Number of top threads (by volume) to read.
        since: Optional lower bound; only messages on or after this date are kept.
        db_path: Path to the SQLite database.

    Returns:
        Validated records, ordered by thread then timestamp. Rows whose body
        cannot be decoded are silently skipped.
    """
    since_ns: int | None = None
    if since is not None:
        midnight = datetime(since.year, since.month, since.day, tzinfo=UTC)
        unix_seconds = midnight.timestamp() - APPLE_EPOCH_OFFSET
        since_ns = int(unix_seconds * 1e9)

    conn = connect_readonly(db_path)
    try:
        records: list[IMessageRecord] = []
        for chat_identifier, _handle in top_threads(conn, top_n):
            for row in _rows_for_thread(conn, chat_identifier, since_ns):
                record = _build_record(row, chat_identifier)
                if record is not None:
                    records.append(record)
        return records
    finally:
        conn.close()


def records_to_events(records: list[IMessageRecord]) -> list[Event]:
    """Project validated records onto canonical events."""
    return [r.to_event() for r in records]


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
        Canonical events from the selected threads, ordered by thread then
        timestamp. Rows whose body cannot be decoded are silently skipped.
    """
    return records_to_events(read_records(top_n, since=since, db_path=db_path))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the iMessage adapter entry point."""
    parser = argparse.ArgumentParser(description="Ingest iMessage history to JSONL.")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top threads.")
    parser.add_argument("--since", type=str, default=None, help="Lower bound YYYY-MM-DD.")
    parser.add_argument("--out", type=str, default=DEFAULT_OUTPUT, help="Output JSONL path.")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to chat.db.")
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Skip persisting events to the unified events table.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: ingest events, write JSONL, and persist to the store.

    The JSONL stays the input the downstream ``episodes`` stage reads. Unless
    ``--no-store`` is given, the same events are also upserted into the unified
    ``events`` table (idempotent on event id), so iMessage and every other source
    share one durable home.
    """
    args = _parse_args(argv)
    since = date.fromisoformat(args.since) if args.since else None
    events = ingest(args.top_n, since=since, db_path=args.db)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    written = write_events_jsonl(events, args.out)
    print(f"Wrote {written} events to {args.out}")
    if not args.no_store:
        stored = persist_events(events)
        print(f"Persisted {stored} events to the unified events table")


if __name__ == "__main__":
    main()
