"""Pydantic model for a single iMessage record from ``chat.db``.

Source: the macOS Messages database at ``~/Library/Messages/chat.db``. Each row
of the ``message`` table (joined to its ``chat``) is one message. The adapter
(``recall/adapters/imessage.py``) reads and decodes those rows — most message bodies
live in an ``attributedBody`` typedstream BLOB rather than the ``text`` column —
and validates them into :class:`IMessageRecord`.

This mirrors :mod:`models.spotify`: a faithful, typed source record that knows
how to project itself onto the canonical :class:`~core.schema.Event` via
:meth:`IMessageRecord.to_event`, so iMessage flows through the same
``store.add_events`` -> ``build_episodes`` -> Hindsight ``retain`` pipeline as
every other source.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from core.schema import Event

#: Apple's Core Data epoch (2001-01-01 UTC) as seconds past the Unix epoch.
#: Defined here (not imported from the adapter) so the model's id derivation is
#: self-contained and does not depend on the adapter layer.
_APPLE_EPOCH_OFFSET = 978_307_200


class IMessageRecord(BaseModel):
    """One decoded iMessage, ready to project onto a canonical event.

    Construction happens in the adapter after the raw ``chat.db`` row has been
    decoded (``attributedBody`` -> text) and its Apple-epoch timestamp converted
    to a timezone-aware UTC :class:`~datetime.datetime`. Keeping that decoding in
    the adapter lets this model stay a clean, validated value object.

    Attributes:
        rowid: ``message.ROWID`` in ``chat.db``; the source-row primary key.
        thread_id: The chat identifier (phone number, email, or group id) the
            message belongs to — becomes the event's ``thread_id``.
        t_utc: Timezone-aware UTC timestamp of the message.
        content: The decoded message text (non-empty; empty rows are skipped
            upstream).
        is_from_me: Whether the account owner sent it; maps to ``author_role``.
        reply_to_guid: GUID of the message this one replies to, if any.
    """

    model_config = ConfigDict(extra="ignore")

    rowid: int
    thread_id: str
    t_utc: datetime
    content: str
    is_from_me: bool
    reply_to_guid: str | None = None

    @property
    def author_role(self) -> str:
        """``"self"`` if the account owner sent it, else ``"other"``."""
        return "self" if self.is_from_me else "other"

    @property
    def raw_ref(self) -> str:
        """Pointer back to the source row: ``chat.db#<ROWID>``.

        The canonical "jump to original" link, identical to the convention the
        legacy ingest used, so existing stored events keep matching.
        """
        return f"chat.db#{self.rowid}"

    def event_id(self) -> str:
        """Deterministic id keyed on the fields that uniquely place a message.

        Uses the historical derivation byte-for-byte —
        ``sha256("{thread_id}|{apple_ns}|{is_from_me}|{content}")[:16]`` — so ids
        are stable across refactors: re-ingesting is idempotent and any
        already-stored events keep matching. The Apple-epoch nanosecond value is
        reconstructed from ``t_utc`` to reproduce the exact key.
        """
        apple_ns = int((self.t_utc.timestamp() - _APPLE_EPOCH_OFFSET) * 1e9)
        is_from_me = 1 if self.is_from_me else 0
        key = f"{self.thread_id}|{apple_ns}|{is_from_me}|{self.content}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def to_event(self) -> Event:
        """Project this message onto the canonical :class:`~core.schema.Event`.

        The seam that puts iMessage on the shared provenance path: the resulting
        event carries ``raw_ref`` back to ``chat.db`` and flows through
        ``store.add_events`` (durable ``events`` table + ``content_sha``),
        ``build_episodes`` windowing, and Hindsight ``retain`` unchanged.
        """
        return Event(
            id=self.event_id(),
            t_utc=self.t_utc,
            author_role=self.author_role,
            content=self.content,
            thread_id=self.thread_id,
            reply_to=self.reply_to_guid,
            raw_ref=self.raw_ref,
            source="imessage",
        )
