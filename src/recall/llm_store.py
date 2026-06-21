"""SQLite persistence for LLM-chat raw_data — a sibling of the events table.

LLM-chat messages (from the Claude export adaptor) are *passive* raw_data just
like iMessage rows, but they live in their own ``llm_messages`` table rather than
sharing :mod:`recall.store`'s ``events`` table. Keeping them in a sibling table —
rather than editing ``store.py`` — gives the LLM-chat path an isolated, owned
schema it can evolve (export-specific columns, retention, privacy audits)
without risking the iMessage/notes rows that already flow through ``events``.
The two tables are deliberately shaped identically: ``llm_messages`` mirrors
:class:`recall.schema.Event` / :class:`models.chat_event.ChatEvent`
field-for-field so downstream code can treat both as the same canonical row.

Each row stores a ``content_sha`` provenance hash (reusing
:func:`recall.store.content_sha`). That hash is the evidence guarantee: it lets
us prove a stored message is byte-identical to what we ingested, independent of
whether the original Claude export is later re-exported, edited, or lost. A
finding derived from an LLM chat can therefore be traced back to a message whose
integrity we can verify on its own.

It is deliberately plain ``sqlite3`` — no ORM, no new dependencies — and follows
the POC's file-based-state philosophy: the DB is a single inspectable file under
``data/`` (the same file ``store.py`` uses is fine, since this is a different
table).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from models.chat_event import ChatEvent
from recall.schema import _parse_utc
from recall.store import content_sha

#: Default on-disk location. The same ``data/recall.db`` file as ``store.py`` is
#: intentional: ``llm_messages`` is a separate table, so the two stores coexist
#: in one inspectable database file.
DEFAULT_DB_PATH = Path("data/recall.db")

_SCHEMA = """
-- Passive raw_data from LLM chats (the Claude export adaptor). A sibling of the
-- ``events`` table in recall.store, mirroring ChatEvent / recall.schema.Event
-- field-for-field so both passive sources share one canonical row shape.
-- content_sha is a provenance hash of the content as ingested: it lets us prove
-- a stored message is byte-identical to what we saw, independent of whether the
-- original Claude export is later re-exported, edited, or unavailable.
CREATE TABLE IF NOT EXISTS llm_messages (
    id           TEXT PRIMARY KEY,
    t_utc        TEXT NOT NULL,
    author_role  TEXT NOT NULL,
    content      TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    reply_to     TEXT,
    raw_ref      TEXT NOT NULL,
    source       TEXT NOT NULL,
    content_sha  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_messages_source ON llm_messages(source);
CREATE INDEX IF NOT EXISTS idx_llm_messages_thread ON llm_messages(thread_id);
"""


class LLMStore:
    """A thin SQLite wrapper for LLM-chat messages (the ``llm_messages`` table).

    Mirrors :class:`recall.store.CapsuleStore`'s connection idiom: each public
    method opens its own short-lived connection so the store is safe to call from
    FastAPI worker threads (connections never cross threads). An in-memory store
    is the exception — its data only lives as long as a connection — so it keeps
    one shared connection open for the store's lifetime.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        """Open (and initialize) the store at ``db_path``.

        Args:
            db_path: Path to the SQLite file. Parent directories are created if
                missing. Use ``":memory:"`` for tests.
        """
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # An in-memory store's data only lives as long as a connection, so keep
        # one open for the store's lifetime; on-disk stores open per call.
        self._shared: sqlite3.Connection | None = (
            self._connect() if self.db_path == ":memory:" else None
        )
        with self._cursor() as cur:
            cur.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        """Yield a cursor in a transaction, committing on success."""
        conn = self._shared or self._connect()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        finally:
            if self._shared is None:
                conn.close()

    def add_llm_messages(self, events: Iterable[ChatEvent]) -> int:
        """Upsert LLM-chat messages (passive raw_data) into the store.

        Idempotent on ``id`` (``INSERT OR REPLACE``) so re-ingesting the same
        Claude export is safe and never duplicates rows. The provenance
        ``content_sha`` is computed from ``content`` at write time, so a re-insert
        with changed content updates the hash to match.

        Args:
            events: Validated :class:`ChatEvent` rows to persist.

        Returns:
            The number of messages written (re-inserts are counted).
        """
        count = 0
        with self._cursor() as cur:
            for e in events:
                cur.execute(
                    "INSERT OR REPLACE INTO llm_messages "
                    "(id, t_utc, author_role, content, thread_id, reply_to, "
                    " raw_ref, source, content_sha) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        e.id,
                        e.t_utc.isoformat(),
                        e.author_role,
                        e.content,
                        e.thread_id,
                        e.reply_to,
                        e.raw_ref,
                        e.source,
                        content_sha(e.content),
                    ),
                )
                count += 1
        return count

    def list_llm_messages(
        self, source: str | None = None, thread_id: str | None = None
    ) -> list[ChatEvent]:
        """Return stored messages, optionally filtered, ordered by ``t_utc``.

        The provenance ``content_sha`` column is not part of
        :class:`ChatEvent`, so it is dropped on the way out; use
        :meth:`verify_llm_message` to check it.

        Args:
            source: If given, return only rows from this source (e.g.
                ``"claude"``).
            thread_id: If given, return only rows in this conversation thread.

        Returns:
            Matching messages as :class:`ChatEvent` rows, oldest first.
        """
        clauses: list[str] = []
        params: list[str] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if thread_id is not None:
            clauses.append("thread_id = ?")
            params.append(thread_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._cursor() as cur:
            rows = cur.execute(
                f"SELECT * FROM llm_messages{where} ORDER BY t_utc", params
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ChatEvent:
        return ChatEvent(
            id=row["id"],
            t_utc=_parse_utc(row["t_utc"]),
            author_role=row["author_role"],
            content=row["content"],
            thread_id=row["thread_id"],
            reply_to=row["reply_to"],
            raw_ref=row["raw_ref"],
            source=row["source"],
        )

    def verify_llm_message(self, message_id: str) -> bool | None:
        """Check a stored message's content against its provenance hash.

        Mirrors :meth:`recall.store.CapsuleStore.verify_event`. This is the
        evidence guarantee: a finding derived from an LLM chat can be traced to a
        message whose integrity we can prove independent of the original export.

        Args:
            message_id: The ``id`` of the message to verify.

        Returns:
            ``True`` if the stored content still matches the hash recorded at
            ingest, ``False`` if it has been tampered with, or ``None`` if no
            message with ``message_id`` exists.
        """
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT content, content_sha FROM llm_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        return content_sha(row["content"]) == row["content_sha"]

    def close(self) -> None:
        """Close the shared connection, if any (no-op for on-disk stores)."""
        if self._shared is not None:
            self._shared.close()
            self._shared = None
