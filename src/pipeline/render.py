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

#: Scalar ``additional_data`` keys that carry render-worthy *meaning* (enrichments),
#: as opposed to storage plumbing (dimensions, paths, flags) which must never leak
#: into retained text. Opt-in by design: adding a new enrichment key requires
#: listing it here. Arrays are intentionally excluded — list-valued enrichments
#: (e.g. ``vision_tags``, ``people``) are surfaced explicitly by the per-source
#: renderer that knows how to phrase them, not folded in generically.
RENDER_KEYS = ("contact_name", "vision_description", "artist_vibe")

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


class BatchRetainClient(Protocol):
    """Minimal client surface the batch retain wrapper needs.

    The real :class:`hindsight_client.Hindsight` and test fakes satisfy this.
    The signature mirrors ``Hindsight.retain_batch`` exactly so structural
    subtyping passes without a cast.
    """

    def retain_batch(
        self,
        bank_id: str,
        items: list[dict[str, Any]],
        document_id: str | None = None,
        document_tags: list[str] | None = None,
        retain_async: bool = False,
    ) -> Any:
        """Store multiple memories in batch; see ``Hindsight.retain_batch``."""
        ...


def _fmt_time(t: datetime) -> str:
    """Render a timestamp as an ISO-8601 string for a templated fact."""
    return t.isoformat()


def _enrichment(event: Event, key: str) -> str | None:
    """Return a non-empty allowlisted scalar enrichment from ``additional_data``.

    Only keys in :data:`RENDER_KEYS` are readable here; everything else in
    ``additional_data`` is storage plumbing and stays out of retained text. A
    missing key, a non-string value, or a blank string all yield ``None`` so the
    caller can fall back to its un-enriched template.

    Args:
        event: The event whose ``additional_data`` is read.
        key: The enrichment key; must be one of :data:`RENDER_KEYS`.

    Returns:
        The trimmed string value, or ``None`` when absent/blank/non-string.
    """
    if key not in RENDER_KEYS:
        return None
    value = (event.additional_data or {}).get(key)
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _transcript_line(event: Event) -> str:
    """Render one conversational event as a ``role: content`` line.

    Args:
        event: A conversational event (``author_role`` and ``content`` set).

    Returns:
        ``"self: hello"`` / ``"other: hi"``; a missing role falls back to
        ``"unknown"`` and missing content to the empty string so a malformed row
        degrades gracefully rather than crashing the render. When the event
        carries a resolved ``contact_name``, a non-self author is labelled by name
        (``"Marleigh: hi"``) instead of the bare ``"other"`` role, which removes
        the LLM's incentive to invent a name during extraction.
    """
    role = event.author_role or "unknown"
    content = event.content or ""
    if role != "self":
        name = _enrichment(event, "contact_name")
        if name is not None:
            role = name
    return f"{role}: {content}"


def _spotify_fact(event: Event) -> str:
    """Render one Spotify play as a templated fact.

    The canonical Spotify event already carries a human-readable description in
    ``content`` (e.g. ``"Listened to 'Track' by Artist (album X)"``). When the
    artist has a cached vibe, ``content`` already folds it in, but we also read
    the ``artist_vibe`` enrichment explicitly and append it when absent from the
    text — so the taste signal is surfaced by intent, not by accident of the
    content line. We prefix the timestamp to form a self-contained fact:
    ``"On {t}, listened to 'Track' by Artist ... [vibe]"``.
    """
    desc = (event.content or "listened to music").strip()
    # Lower-case the leading verb so it reads as one sentence after "On {t}, ".
    if desc[:9] == "Listened ":
        desc = "listened" + desc[8:]
    vibe = _enrichment(event, "artist_vibe")
    if vibe is not None and vibe not in desc:
        desc = f"{desc} ({vibe})"
    return f"On {_fmt_time(event.t_utc)}, {desc}"


def _photo_fact(event: Event) -> str:
    """Render one photo as a templated fact from ``additional_data``.

    When the photo has been vision-enriched, its ``vision_description`` carries the
    scene ("a golden sunset over the sea from a cozy window sill") and becomes the
    body of the fact — this is what gives photos real semantic content instead of
    a bare coordinate. Without it, we fall back to the raw place template. Named
    people (a list, handled explicitly here rather than via the scalar allowlist)
    are appended when present.
    """
    data = event.additional_data or {}
    description = _enrichment(event, "vision_description")
    if description is not None:
        body = description
    else:
        lat, lng = data.get("lat"), data.get("lng")
        place = f"{lat}, {lng}" if lat is not None and lng is not None else "an unknown location"
        body = f"took a photo at {place}"
    people = [p for p in (data.get("people") or []) if p]
    who = f" with {', '.join(people)}" if people else ""
    return f"On {_fmt_time(event.t_utc)}, {body}{who}"


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


def build_batch_item(
    unit: Any,
    text: str,
    *,
    author_role: str | None,
) -> dict[str, Any]:
    """Build one ``retain_batch`` item dict for a rendered unit.

    Each item carries its own ``document_id = unit.unit_id`` so provenance is
    preserved per unit (not collapsed onto a batch-level id). Tags and network
    routing match what :func:`retain_unit` produces for a single call.

    Args:
        unit: The rung-① unit; ``unit_id`` and ``t_start`` are read.
        text: Non-empty rendered text from :func:`render_unit`.
        author_role: ``"self"``, ``"other"``, or ``None`` — drives network routing.

    Returns:
        A dict suitable for inclusion in the ``items`` list of ``retain_batch``.

    Raises:
        ValueError: If ``text`` is blank.
    """
    if not text.strip():
        raise ValueError("build_batch_item requires non-empty rendered text")
    network = _ROLE_NETWORK.get(author_role or "", "world")
    return {
        "content": text,
        "timestamp": unit.t_start.isoformat(),
        "document_id": unit.unit_id,
        "tags": [unit.source, f"author:{author_role or 'unknown'}", f"network:{network}"],
    }


def retain_batch_units(
    client: BatchRetainClient,
    items: list[dict[str, Any]],
    *,
    bank_id: str = DEFAULT_BANK,
) -> None:
    """Retain a pre-assembled list of batch items into Hindsight.

    Each item must already carry its own ``document_id`` (built by
    :func:`build_batch_item`). No batch-level ``document_id`` is passed so the
    orchestrator routes each item under its own document — provenance is
    per-unit, not per-batch.

    Args:
        client: A client exposing :meth:`retain_batch`.
        items: Non-empty list of dicts from :func:`build_batch_item`.
        bank_id: Target Hindsight bank.

    Raises:
        ValueError: If ``items`` is empty.
    """
    if not items:
        raise ValueError("retain_batch_units requires at least one item")
    client.retain_batch(bank_id=bank_id, items=items)
