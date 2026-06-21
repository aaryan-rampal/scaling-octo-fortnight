"""Rung ② — render a memory-ready ``Unit`` to text and retain it.

A ``Unit`` (rung ①) is a coherent run of canonical :class:`~core.schema.Event`
rows. This module turns that run into a single block of text that Hindsight's
``retain`` extracts facts from, then wraps the retain call so it records a
``MemoryRef`` mapping the stored memory back to its unit (provenance).

Rendering follows the research doc (``docs/raw-to-principles-research.md`` §2):

- **Conversational** sources (imessage, claude) pass their transcript through as
  role-prefixed lines in time order — ``retain`` is built for conversation-level
  input.
- **Structured** sources (spotify, photos) become one **templated fact per
  event**. Multimodal/structured rows are converted to text by template, never
  by VLM/LLM captioning, because caption hallucination would propagate into
  stored "facts".

The retain wrapper does **not** run live during the build; it is exercised with
a fake client in tests. The real call happens only when the assembled pipeline
runs under Doppler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.schema import Event

#: Sources whose events carry a conversational transcript (role + content).
CONVERSATIONAL_SOURCES = frozenset({"imessage", "claude"})

#: Default memory bank the retain wrapper writes to (mirrors the iMessage POC).
DEFAULT_BANK = "imessage-v0"

#: How ``author_role`` routes a memory across Hindsight networks (research §2):
#: the user's own actions become first-person Experience; everyone else's become
#: objective World facts. Passed through as a tag/metadata so routing is explicit.
_ROLE_NETWORK = {"self": "experience", "other": "world"}


@dataclass(frozen=True, slots=True)
class MemoryRef:
    """Provenance row linking the memories of one retain back to their source unit.

    Hindsight's ``retain`` returns no per-memory id (its response carries only an
    operation status), and the ``metadata`` passed to ``retain`` does not persist
    on the extracted memories. The durable link that *does* persist is the
    **``document_id``**: we pass ``document_id = unit.unit_id`` into ``retain``, and
    every memory Hindsight extracts from that text comes back carrying it. So the
    trace is ``memory.document_id == unit.unit_id`` → unit → raw Events; the real
    per-memory UUIDs are read later from ``list_memories`` / ``recall`` (which do
    expose ``id``), keyed by this ``document_id``.

    Attributes:
        document_id: The id passed to ``retain`` (equals the source ``unit_id``);
            persisted on every memory extracted from the unit.
        derived_from: The ``Unit.unit_id`` value(s) the memories came from. Always
            non-empty — an empty derivation is a snapped provenance chain and is
            rejected at construction time.
    """

    document_id: str
    derived_from: list[str]

    def __post_init__(self) -> None:
        """Reject an empty ``derived_from`` (the provenance fail-fast rule)."""
        if not self.derived_from:
            raise ValueError("MemoryRef.derived_from must be a non-empty list")


class RetainClient(Protocol):
    """Minimal client surface the retain wrapper needs.

    Both the real :class:`hindsight_client.Hindsight` and the test fake satisfy
    this; it isolates the wrapper from the full client so it stays unit-testable
    without a network or server.
    """

    def retain(self, *args: Any, **kwargs: Any) -> Any:
        """Store one memory; see ``Hindsight.retain`` for full semantics."""
        ...


def _fmt_time(t: datetime) -> str:
    """Render a timestamp as an ISO-8601 string for a templated fact."""
    return t.isoformat()


def _transcript_line(event: Event) -> str:
    """Render one conversational event as a ``role: content`` line.

    Args:
        event: A conversational event (``author_role`` and ``content`` set).

    Returns:
        ``"self: hello"`` / ``"other: hi"``; a missing role falls back to
        ``"unknown"`` and missing content to the empty string so a malformed row
        degrades gracefully rather than crashing the render.
    """
    role = event.author_role or "unknown"
    content = event.content or ""
    return f"{role}: {content}"


def _spotify_fact(event: Event) -> str:
    """Render one Spotify play as a templated fact.

    The canonical Spotify event already carries a human-readable description in
    ``content`` (e.g. ``"Listened to 'Track' by Artist (album X)"``); its
    ``additional_data`` is empty. We prefix it with the timestamp to form a
    self-contained fact: ``"On {t}, listened to 'Track' by Artist ..."``.
    """
    desc = (event.content or "listened to music").strip()
    # Lower-case the leading verb so it reads as one sentence after "On {t}, ".
    if desc[:9] == "Listened ":
        desc = "listened" + desc[8:]
    return f"On {_fmt_time(event.t_utc)}, {desc}"


def _photo_fact(event: Event) -> str:
    """Render one photo as a templated fact from ``additional_data``.

    Uses place (lat/lng when present) and named people; people may be empty and
    is handled gracefully. ``"On {t}, took a photo at {lat,lng} with {people}"``.
    """
    data = event.additional_data or {}
    lat, lng = data.get("lat"), data.get("lng")
    place = f"{lat}, {lng}" if lat is not None and lng is not None else "an unknown location"
    people = [p for p in (data.get("people") or []) if p]
    who = f" with {', '.join(people)}" if people else ""
    return f"On {_fmt_time(event.t_utc)}, took a photo at {place}{who}"


def render_unit(unit: Any, events: list[Event]) -> str:
    """Render a unit's events to a single block of text for ``retain``.

    Args:
        unit: The rung-① unit; only its ``source`` is read here. Its events are
            passed in via ``events`` (this function never queries the DB).
        events: The unit's events, already in time order.

    Returns:
        Conversational sources: the role-prefixed transcript, one line per event.
        Spotify / photos: one templated fact per event, newline-joined.

    Raises:
        ValueError: If ``events`` is empty — a unit always has at least one event.
    """
    if not events:
        raise ValueError("render_unit requires at least one event")
    source = unit.source
    if source in CONVERSATIONAL_SOURCES:
        return "\n".join(_transcript_line(e) for e in events)
    if source == "spotify":
        return "\n".join(_spotify_fact(e) for e in events)
    if source == "photos":
        return "\n".join(_photo_fact(e) for e in events)
    # Unknown structured source: fall back to whatever text content exists, so a
    # new source still produces *something* retainable rather than crashing.
    return "\n".join((e.content or "").strip() for e in events if e.content)


def retain_unit(
    client: RetainClient,
    unit: Any,
    text: str,
    *,
    author_role: str | None,
    bank_id: str = DEFAULT_BANK,
) -> MemoryRef:
    """Retain rendered unit text into Hindsight and return its provenance ref.

    Passes ``author_role`` through as a tag and metadata so self→Experience /
    others→World routing is explicit rather than left implicit (research §2). The
    returned :class:`MemoryRef` carries the unit's ``unit_id`` as ``derived_from``
    so rung ③ can trace any memory back to its source unit.

    Args:
        client: A client exposing :meth:`retain` (real or a test fake).
        unit: The rung-① unit being retained; ``unit_id`` and ``t_start`` are read.
        text: The rendered text from :func:`render_unit`.
        author_role: ``"self"``, ``"other"``, or ``None`` — drives network routing.
        bank_id: Target Hindsight bank.

    Returns:
        A :class:`MemoryRef` with the retained memory id and the unit's id.

    Raises:
        ValueError: If ``text`` is blank — there is nothing to retain.
    """
    if not text.strip():
        raise ValueError("retain_unit requires non-empty rendered text")
    network = _ROLE_NETWORK.get(author_role or "", "world")
    client.retain(
        bank_id=bank_id,
        content=text,
        timestamp=unit.t_start.isoformat(),
        document_id=unit.unit_id,
        tags=[unit.source, f"author:{author_role or 'unknown'}", f"network:{network}"],
    )
    return MemoryRef(document_id=unit.unit_id, derived_from=[unit.unit_id])
