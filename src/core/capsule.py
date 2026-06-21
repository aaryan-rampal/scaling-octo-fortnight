"""Capsule and media schema for the active (user-created) capture path.

A :class:`Capsule` is a user-created memory: a place plus one or more pieces of
media (photo / audio / video / text). It is the *active* counterpart to the
passive iMessage ingest path — raw_data created intentionally by the user rather
than scraped from a source. Capsules persist in the SQLite store (see
:mod:`storage.store`) and later feed the same canonical :class:`~core.schema.Event`
pipeline that passive sources do.

This is distinct from the swarm-facing ``TimeCapsule`` in
``design/TIME_CAPSULE_FLYWHEEL.md`` (a raw_data-refs + intent bundle that the
agentic swarm tests against principles). A :class:`Capsule` is the *captured
memory* itself; that flywheel object queries against it. They do not share a name
on purpose.

Both dataclasses serialize to and from plain dicts with ISO-8601 timestamps,
mirroring :mod:`core.schema`, so they round-trip cleanly through JSON and the
SQLite store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.schema import Event, _parse_utc

#: Allowed media kinds. Kept permissive and explicit so the API can validate
#: uploads without guessing from MIME alone.
MEDIA_KINDS = ("photo", "audio", "video", "text")

#: ``source`` tag for capsule-born events in the unified ``events`` table.
CAPSULE_SOURCE = "capsule"


@dataclass(frozen=True, slots=True)
class Media:
    """A single piece of media attached to a capsule.

    The binary itself lives on disk (``file_path``); this record holds only the
    reference and metadata, so SQLite stays small and the original file is
    preserved for downstream EXIF / affect processing.

    Attributes:
        id: Stable identifier for this media item.
        capsule_id: ``id`` of the owning :class:`Capsule`.
        kind: One of :data:`MEDIA_KINDS` (``"photo" | "audio" | "video" | "text"``).
        file_path: Path to the stored file, relative to the media root.
        mime: MIME type reported on upload (e.g. ``"image/jpeg"``).
        byte_size: Size of the stored file in bytes.
        exif_t: Capture time parsed from EXIF, if present.
        exif_lat: Latitude parsed from EXIF GPS, if present.
        exif_lng: Longitude parsed from EXIF GPS, if present.
    """

    id: str
    capsule_id: str
    kind: str
    file_path: str
    mime: str
    byte_size: int
    exif_t: datetime | None = None
    exif_lat: float | None = None
    exif_lng: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict with an ISO timestamp."""
        return {
            "id": self.id,
            "capsule_id": self.capsule_id,
            "kind": self.kind,
            "file_path": self.file_path,
            "mime": self.mime,
            "byte_size": self.byte_size,
            "exif_t": self.exif_t.isoformat() if self.exif_t else None,
            "exif_lat": self.exif_lat,
            "exif_lng": self.exif_lng,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Media:
        """Reconstruct a :class:`Media` from a serialized dict."""
        exif_t = data.get("exif_t")
        return cls(
            id=data["id"],
            capsule_id=data["capsule_id"],
            kind=data["kind"],
            file_path=data["file_path"],
            mime=data["mime"],
            byte_size=data["byte_size"],
            exif_t=_parse_utc(exif_t) if exif_t else None,
            exif_lat=data.get("exif_lat"),
            exif_lng=data.get("exif_lng"),
        )


@dataclass(frozen=True, slots=True)
class Capsule:
    """A user-created captured memory: a place and its attached media.

    Mood is intentionally *not* captured here — affect is derived downstream from
    the media (VLM on photos, prosody on audio), so the capture stays to raw
    signal. ``lat``/``lng`` are optional because a user may name a place without
    granting geolocation, and most media has sparse GPS.

    Attributes:
        id: Stable identifier for the capsule.
        created_at: Timezone-aware UTC time the capsule was sealed.
        place_name: Human-readable place label entered by the user.
        lat: Latitude of the place, if provided.
        lng: Longitude of the place, if provided.
        media: Media items belonging to this capsule.
    """

    id: str
    created_at: datetime
    place_name: str
    lat: float | None = None
    lng: float | None = None
    media: list[Media] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict with an ISO timestamp."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "place_name": self.place_name,
            "lat": self.lat,
            "lng": self.lng,
            "media": [m.to_dict() for m in self.media],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Capsule:
        """Reconstruct a :class:`Capsule` from a serialized dict."""
        return cls(
            id=data["id"],
            created_at=_parse_utc(data["created_at"]),
            place_name=data["place_name"],
            lat=data.get("lat"),
            lng=data.get("lng"),
            media=[Media.from_dict(m) for m in data.get("media", [])],
        )

    def to_event(self, note: str | None = None) -> Event:
        """Project this capsule onto the canonical :class:`~core.schema.Event`.

        The seam that puts user-created capsules on the **same provenance path**
        as the passive sources (iMessage / Spotify / photos): the resulting event
        is persisted into the unified ``events`` table, so a capsule is a
        traceable raw_data row that can rise into memory — the active counterpart
        to passive ingest, matching the flywheel's "a capsule births raw_data".

        A capsule is *intentionally created by the user*, so ``author_role`` is
        ``"self"``. Place, geo, and media references ride in ``additional_data``;
        ``thread_id`` is left ``None`` — a capsule is a standalone moment, not a
        conversation thread.

        ``content`` defaults to ``None`` here to keep this projection pure (no
        disk I/O): the journal note lives in a ``text`` media file on disk, and
        the binaries are deliberately not read at this layer. Callers that have
        the note text in hand (e.g. the upload service) can pass ``note`` to set
        ``content`` — first-person text is the strongest grounding the flywheel
        doc names, so surfacing it is worthwhile when available.
        """
        return Event(
            id=self.id,
            t_utc=self.created_at,
            author_role="self",
            content=note,
            thread_id=None,
            reply_to=None,
            raw_ref=f"capsule#{self.id}",
            source=CAPSULE_SOURCE,
            additional_data={
                "place_name": self.place_name,
                "lat": self.lat,
                "lng": self.lng,
                "media": [
                    {"id": m.id, "kind": m.kind, "file_path": m.file_path, "mime": m.mime}
                    for m in self.media
                ],
            },
        )
