"""Canonical event and episode schema for recall.

Events are atomic messages drawn from a source (currently iMessage). Episodes
group a contiguous run of events within a single thread. Both serialize to and
from plain dicts with ISO-8601 timestamps so they round-trip through JSONL.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware datetime.

    Args:
        value: ISO-8601 string, optionally using a trailing ``Z`` for UTC.

    Returns:
        The parsed datetime, guaranteed to carry timezone info.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class Event:
    """A single message-level event.

    Conversational sources (iMessage, Claude) fill ``author_role``, ``content``,
    and ``thread_id``; non-conversational sources (photos) leave them ``None``
    and carry their source-specific fields in ``additional_data`` instead.

    Attributes:
        id: Stable hash identifying this event.
        t_utc: Timezone-aware UTC timestamp of the event.
        author_role: ``"self"`` if sent by the account owner, ``"other"`` for a
            counterpart, or ``None`` for non-conversational sources.
        content: Plain-text body, or ``None`` for non-conversational sources.
        thread_id: Conversation the event belongs to, or ``None`` for
            non-conversational sources.
        reply_to: ``id`` of the event this one replies to, if any.
        raw_ref: Reference back to the source row (e.g. ``"chat.db#ROWID"``).
        source: Originating system; defaults to ``"imessage"``.
        additional_data: Source-specific fields that are not shared by all
            sources (e.g. a photo's geo / dimensions / people). Empty for
            sources that fit the canonical fields exactly.
    """

    id: str
    t_utc: datetime
    author_role: str | None
    content: str | None
    thread_id: str | None
    reply_to: str | None
    raw_ref: str
    source: str = "imessage"
    additional_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict with an ISO timestamp."""
        return {
            "id": self.id,
            "t_utc": self.t_utc.isoformat(),
            "author_role": self.author_role,
            "content": self.content,
            "thread_id": self.thread_id,
            "reply_to": self.reply_to,
            "raw_ref": self.raw_ref,
            "source": self.source,
            "additional_data": dict(self.additional_data),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        """Reconstruct an :class:`Event` from a serialized dict."""
        return cls(
            id=data["id"],
            t_utc=_parse_utc(data["t_utc"]),
            author_role=data.get("author_role"),
            content=data.get("content"),
            thread_id=data.get("thread_id"),
            reply_to=data.get("reply_to"),
            raw_ref=data["raw_ref"],
            source=data.get("source", "imessage"),
            additional_data=data.get("additional_data") or {},
        )


@dataclass(frozen=True)
class Episode:
    """A contiguous run of events within one thread.

    Attributes:
        id: Stable identifier for the episode.
        thread_id: Thread the episode belongs to.
        t_start: Timestamp of the first event.
        t_end: Timestamp of the last event.
        participants: Author roles or handles present in the episode.
        events: Ordered events that make up the episode.
    """

    id: str
    thread_id: str
    t_start: datetime
    t_end: datetime
    participants: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict with ISO timestamps."""
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "t_start": self.t_start.isoformat(),
            "t_end": self.t_end.isoformat(),
            "participants": list(self.participants),
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Episode:
        """Reconstruct an :class:`Episode` from a serialized dict."""
        return cls(
            id=data["id"],
            thread_id=data["thread_id"],
            t_start=_parse_utc(data["t_start"]),
            t_end=_parse_utc(data["t_end"]),
            participants=list(data.get("participants", [])),
            events=[Event.from_dict(e) for e in data.get("events", [])],
        )


def write_events_jsonl(events: Iterable[Event], path: str) -> int:
    """Write events to a JSONL file, one serialized event per line.

    Args:
        events: Events to serialize.
        path: Destination file path; overwritten if it exists.

    Returns:
        The number of events written.
    """
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False))
            fh.write("\n")
            count += 1
    return count


def read_events_jsonl(path: str) -> list[Event]:
    """Read events back from a JSONL file produced by :func:`write_events_jsonl`."""
    events: list[Event] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(Event.from_dict(json.loads(line)))
    return events
