"""Pydantic models for the Spotify **Extended Streaming History** export.

Source: the ``Spotify Extended Streaming History/`` folder of a personal data
download — one JSON array per year of ``Streaming_History_Audio_*.json`` and
``Streaming_History_Video_*.json`` files. Audio and video records share an
identical schema, so a single model covers both.

Each record is one *play* (a listen/watch session), not a track: the same track
appears once per time it was played. Music plays carry the
``master_metadata_*`` fields; podcast plays carry ``episode_*`` /
``spotify_episode_uri`` instead, and audiobook plays carry ``audiobook_*``. The
model keeps every field optional so all three shapes validate, and exposes
:meth:`SpotifyStreamRecord.kind` to tell them apart.

Field names in the export are long and snake-cased (e.g.
``master_metadata_track_name``); we keep readable Python attribute names and map
them with :class:`~pydantic.Field` aliases, so a raw record validates directly
with ``SpotifyStreamRecord.model_validate(record)``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.schema import Event

#: thread_id all Spotify plays share, so the gap-windowing in
#: ``pipeline.episodes`` collapses consecutive plays into listening-session
#: episodes (one timeline). Change here if we later bucket per-artist / per-day.
SPOTIFY_THREAD_ID = "spotify:listening"

#: Distinguishes the three content shapes a single record can represent.
StreamKind = Literal["music", "podcast", "audiobook", "unknown"]


class SpotifyStreamRecord(BaseModel):
    """One streaming-history record: a single play of a track / episode / chapter.

    Mirrors the export's JSON shape one-to-one (via aliases) so a raw record
    validates without manual mapping. Validation by *alias* is what makes
    ``model_validate(raw_export_dict)`` work; ``populate_by_name`` additionally
    lets callers construct instances with the readable Python names in tests.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # ---- when / where -------------------------------------------------------
    #: Timestamp the play *stopped* (UTC). Pydantic parses the ISO-8601 string.
    ts: datetime
    platform: str | None = None
    #: Milliseconds of the track/episode actually played in this session.
    ms_played: int = 0
    conn_country: str | None = None
    ip_addr: str | None = None

    # ---- music (master_metadata_*) ------------------------------------------
    track_name: str | None = Field(default=None, alias="master_metadata_track_name")
    artist_name: str | None = Field(default=None, alias="master_metadata_album_artist_name")
    album_name: str | None = Field(default=None, alias="master_metadata_album_album_name")
    #: e.g. ``spotify:track:7lvDsmTRXFE3dK4OjvRiWB``.
    track_uri: str | None = Field(default=None, alias="spotify_track_uri")

    # ---- podcast ------------------------------------------------------------
    episode_name: str | None = None
    episode_show_name: str | None = None
    episode_uri: str | None = Field(default=None, alias="spotify_episode_uri")

    # ---- audiobook ----------------------------------------------------------
    audiobook_title: str | None = None
    audiobook_uri: str | None = None
    audiobook_chapter_title: str | None = None
    audiobook_chapter_uri: str | None = None

    # ---- playback context ---------------------------------------------------
    #: Why playback started / ended, e.g. ``"trackdone"``, ``"fwdbtn"``, ``"logout"``.
    reason_start: str | None = None
    reason_end: str | None = None
    shuffle: bool | None = None
    skipped: bool | None = None
    offline: bool | None = None
    #: Unix seconds the play happened while offline (0/None when online).
    offline_timestamp: int | None = None
    incognito_mode: bool | None = None

    @property
    def kind(self) -> StreamKind:
        """Classify the record by which content fields are populated."""
        if self.track_uri or self.track_name:
            return "music"
        if self.episode_uri or self.episode_name:
            return "podcast"
        if self.audiobook_uri or self.audiobook_title:
            return "audiobook"
        return "unknown"

    @property
    def track_id(self) -> str | None:
        """Bare Spotify track id, parsed from ``track_uri`` (``None`` if absent)."""
        if not self.track_uri:
            return None
        return self.track_uri.rsplit(":", 1)[-1]

    @property
    def display_title(self) -> str | None:
        """Best human label for the play, regardless of content kind."""
        return self.track_name or self.episode_name or self.audiobook_chapter_title

    @property
    def raw_ref(self) -> str:
        """Pointer back to the source play: content uri (or title) plus its ``ts``.

        Mirrors the iMessage ``chat.db#ROWID`` convention so a finding can be
        traced to the exact play it was built from. The ``ts`` disambiguates
        repeat plays of the same track, which share a uri.
        """
        ref = self.track_uri or self.episode_uri or self.audiobook_uri
        # track/episode/audiobook uris already carry a ``spotify:`` prefix; only
        # title fallbacks need one added, so the ref reads cleanly either way.
        prefix = "" if ref else "spotify:"
        ref = ref or self.display_title
        return f"{prefix}{ref}#{self.ts.isoformat()}"

    def event_id(self) -> str:
        """Deterministic, collision-resistant id derived from :attr:`raw_ref`.

        Idempotent on re-import: the same play always yields the same id, so
        ``store.add_events`` (INSERT OR REPLACE) is safe to re-run.
        """
        return hashlib.sha256(self.raw_ref.encode("utf-8")).hexdigest()[:16]

    def content_line(self) -> str:
        """Render the play as a readable line for the canonical ``Event``.

        Music: ``"Listened to 'Track' by Artist (album Album)"``; podcasts and
        audiobooks fall back to their own labels. This text is what reaches
        Hindsight and the principles graph, so it stays human-readable.
        """
        if self.kind == "music":
            title = self.track_name or "unknown track"
            artist = self.artist_name or "unknown artist"
            line = f"Listened to '{title}' by {artist}"
            if self.album_name:
                line += f" (album {self.album_name})"
            return line
        if self.kind == "podcast":
            show = self.episode_show_name
            ep = self.episode_name or "unknown episode"
            return f"Listened to podcast '{ep}'" + (f" from {show}" if show else "")
        if self.kind == "audiobook":
            chapter = self.audiobook_chapter_title or "a chapter"
            book = self.audiobook_title
            return f"Listened to '{chapter}'" + (f" from {book}" if book else "")
        return f"Played {self.display_title or 'unknown content'}"

    def to_event(self) -> Event:
        """Project this play onto the canonical :class:`~core.schema.Event`.

        This is the seam that puts Spotify on the same provenance path as
        iMessage: the resulting event flows through ``store.add_events`` (the
        durable ``events`` table, with its ``content_sha`` integrity hash),
        ``build_episodes`` windowing, and Hindsight ``retain`` unchanged.

        ``author_role`` is always ``"self"`` — a play is the user's own action.
        """
        return Event(
            id=self.event_id(),
            t_utc=self.ts,
            author_role="self",
            content=self.content_line(),
            thread_id=SPOTIFY_THREAD_ID,
            reply_to=None,
            raw_ref=self.raw_ref,
            source="spotify",
        )
