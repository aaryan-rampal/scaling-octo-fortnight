"""Parse-time model for a single Apple Photos asset (``PhotoRecord``).

A ``PhotoRecord`` is the source-parse row for one photo or video drawn from the
local ``Photos.sqlite``. Photos are not conversational, so :meth:`to_event`
projects a record onto a canonical :class:`~recall.schema.Event` that leaves the
conversational fields (``author_role`` / ``content`` / ``thread_id`` /
``reply_to``) empty and carries the photo-only metadata in ``additional_data``.
This puts photos on the **same provenance path as every other source**: the
emitted events go through ``adaptors._persist.persist_events`` into the unified
``events`` table, no source-specific storage needed.

Pydantic is used (over the frozen dataclasses elsewhere) because the source rows
come straight out of a third-party SQLite schema we do not control: strict
validation catches a column drifting type or a flag arriving as something other
than a bool, failing loud at ingest instead of silently corrupting the store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from recall.schema import Event

#: ``source`` discriminator stamped on every photo-derived canonical event.
PHOTO_SOURCE = "photos"


class PhotoRecord(BaseModel):
    """One photo or video asset's metadata, with provenance back to the source.

    No binary is ever copied: ``original_path`` references the original on disk so
    the recall DB stays small (same philosophy as ``Media.file_path``). Only
    *named* people are recorded; anonymous face clusters are dropped because their
    cluster ids carry no human meaning.

    Attributes:
        id: Stable identifier for the asset (the Photos ``ZUUID``).
        captured_at: Timezone-aware UTC capture time (Apple Core Data epoch
            converted to UTC at ingest).
        lat: Latitude in degrees, or ``None`` when GPS is absent (the source's
            ``(-180, -180)`` sentinel is mapped to ``None``).
        lng: Longitude in degrees, or ``None`` when GPS is absent.
        original_filename: The user-facing original filename (``ZORIGINALFILENAME``).
        original_path: Library-relative path to the original on disk,
            ``originals/<ZDIRECTORY>/<ZFILENAME>``. The binary is never read.
        width: Pixel width of the asset.
        height: Pixel height of the asset.
        is_favorite: Whether the user flagged the asset as a favorite.
        is_hidden: Whether the asset is in the Hidden album.
        is_trashed: Whether the asset is in the Recently Deleted album.
        kind: ``"photo"`` or ``"video"`` (from the source ``ZKIND`` enum).
        people: Display names of *named* people detected in the asset; anonymous
            clusters are excluded. Empty when no named person is present.
        raw_ref: Exact source reference, ``photos.sqlite#<ZASSET.Z_PK>`` — the
            provenance link that must survive even if the library is rebuilt.
    """

    id: str
    captured_at: datetime
    lat: float | None
    lng: float | None
    original_filename: str
    original_path: str
    width: int
    height: int
    is_favorite: bool
    is_hidden: bool
    is_trashed: bool
    kind: Literal["photo", "video"]
    people: list[str]
    raw_ref: str

    def to_event(self) -> Event:
        """Project this photo onto the canonical :class:`~recall.schema.Event`.

        The seam that puts photos on the shared provenance path. Photos are not
        conversational, so ``author_role`` / ``content`` / ``thread_id`` /
        ``reply_to`` are left ``None`` and the photo-only metadata (geo,
        dimensions, flags, people, on-disk path) rides in ``additional_data``.
        ``captured_at`` becomes the event's ``t_utc``.
        """
        return Event(
            id=self.id,
            t_utc=self.captured_at,
            author_role=None,
            content=None,
            thread_id=None,
            reply_to=None,
            raw_ref=self.raw_ref,
            source=PHOTO_SOURCE,
            additional_data={
                "lat": self.lat,
                "lng": self.lng,
                "original_filename": self.original_filename,
                "original_path": self.original_path,
                "width": self.width,
                "height": self.height,
                "is_favorite": self.is_favorite,
                "is_hidden": self.is_hidden,
                "is_trashed": self.is_trashed,
                "kind": self.kind,
                "people": self.people,
            },
        )
