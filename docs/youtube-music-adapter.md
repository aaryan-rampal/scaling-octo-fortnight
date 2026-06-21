# Design Doc — YouTube Music Adapter (vs. the Spotify adapter)

How our existing **Spotify Extended Streaming History** adapter would change if we
swapped the source to **YouTube Music**. This is a design doc, not an
implementation: the goal is to size the change against our current pattern and be
honest about what maps cleanly, what is lossy, and what is impossible.

The pattern we already have (see [`docs/api-contract.md`](api-contract.md) for the
broader raw_data story) is: a typed source model mirrors the export JSON → the
model projects itself onto a canonical [`Event`](../src/recall/schema.py) via
`to_event()` → the adapter walks the export, validates, projects, and persists
through the shared [`persist_events`](../src/adaptors/_persist.py) into the one
unified `events` table in [`CapsuleStore`](../src/recall/store.py).

---

## Summary

The change is **mostly a new model, almost no new architecture**. The canonical
`Event` target, the `to_event()` seam, `persist_events` / the unified `events`
table, and the adapter's `walk → validate → project → persist` shape are all
unchanged — that abstraction is exactly what makes a source swap cheap. What's
genuinely new is a `models/youtube_music.py` that mirrors Google Takeout's
`watch-history.json` record shape (which looks nothing like Spotify's), plus a
thin `adaptors/youtube_music.py` to walk Takeout's layout. The hard part is **not
code**, it's **data loss**: Takeout has no per-play duration, no clean
artist/album split, and no shuffle/skip/reason signals, and it mixes ordinary
YouTube video views in with YT Music plays. So the model is new, the projection
is lossier, but the seam holds.

---

## What stays the same

The whole point of the `to_event()` seam is that downstream code never learns a
new source exists. Concretely, none of these change:

- **The canonical target.** Both adapters emit the same frozen
  [`Event`](../src/recall/schema.py) dataclass — `id`, `t_utc`, `author_role`,
  `content`, `thread_id`, `reply_to`, `raw_ref`, `source`. YouTube Music produces
  the same shape; only `source="youtube_music"` differs.
- **The `to_event()` pattern.** Exactly as in
  [`SpotifyStreamRecord.to_event`](../src/models/spotify.py) and
  [`IMessageRecord.to_event`](../src/models/imessage.py): the model owns its own
  projection, including `event_id()`, `raw_ref`, and `content_line()`.
- **Persistence + the unified table.** Events flow through
  [`persist_events`](../src/adaptors/_persist.py) →
  `CapsuleStore.add_events` (`INSERT OR REPLACE`, idempotent on `id`,
  `content_sha` provenance hash). No schema migration: the `events` table is
  already source-agnostic via its `source` column.
- **The adapter shape.** A YouTube Music adapter is a near-copy of
  [`adaptors/spotify.py`](../src/adaptors/spotify.py): a `read_records()`
  generator that walks the export and validates each raw dict, a
  `records_to_events()` projector, an `ingest()` that composes them, and a
  `main()` CLI that writes JSONL + calls `persist_events`. The control flow is
  identical; only the file-walking and the filter predicate differ.
- **Downstream stages.** `build_episodes` windowing and Hindsight `retain` are
  untouched — they consume `Event`s and don't care about the origin.

The takeaway: the abstraction holds. A source swap is a new model + a thin
adapter, not a re-architecture.

---

## What changes

Two new files, mirroring the Spotify pair:

- `src/models/youtube_music.py` — a `YouTubeMusicRecord` pydantic model mirroring
  one Takeout `watch-history.json` record.
- `src/adaptors/youtube_music.py` — the walker/validator/projector + CLI.

### The source: Google Takeout `watch-history.json`

The realistic acquisition route is **Google Takeout → "YouTube and YouTube
Music" → history → `watch-history.json`** (you must select **JSON** in Takeout's
"multiple formats" option; the default is HTML). YouTube Music plays are *not* a
separate export — they are interleaved into the single watch history alongside
ordinary YouTube video views. The file is **one JSON array of records** (not a
per-year folder like Spotify), so the adapter walks one file (or a small fixed
set), not a glob of yearly files.

A representative record looks like this (field names verified against Takeout's
schema; values illustrative):

```json
{
  "header": "YouTube Music",
  "title": "Watched Bohemian Rhapsody",
  "titleUrl": "https://www.youtube.com/watch?v=fJ9rUzIMcZQ",
  "subtitles": [
    { "name": "Queen Official", "url": "https://www.youtube.com/channel/UC..." }
  ],
  "time": "2024-03-14T22:01:55.123Z",
  "products": ["YouTube"],
  "activityControls": ["YouTube watch history"]
}
```

Field notes (and honest uncertainty):

- `header` — the surface the activity came from. For music plays this is the
  string **`"YouTube Music"`**; ordinary video views show **`"YouTube"`**. This
  is our primary music-vs-video discriminator (see filtering below).
- `title` — a human string, usually prefixed with a verb, e.g.
  `"Watched <song/video title>"` (and `"Listened to <…>"` has been seen for some
  Music entries). The prefix is locale-dependent and not a stable field, so we
  treat `title` as opaque display text, not a parseable structure.
- `titleUrl` — the watch URL; the `v=` query param is the **videoId**, our only
  stable per-item identifier. May be **absent** on deleted/private videos.
- `subtitles[0].name` — the channel name. For Music this is the closest thing to
  an artist (often `"<Artist> - Topic"` for auto-generated Music channels), but
  it is *not* a clean artist field. `subtitles` may be **absent**.
- `time` — ISO-8601 UTC timestamp. Unlike Spotify's `ts` (play *end*), this is
  effectively the **start/occurrence** time of the event; there is no end time.
- `products` — coarse product tags, e.g. `["YouTube"]`. Note this is `"YouTube"`
  even for Music entries in some exports, so `products` is a weaker signal than
  `header` for the music/video split. *Uncertain across Takeout versions — treat
  `header` as authoritative and `products` as a fallback hint.*
- `activityControls` — which history toggle recorded this; not useful to us.

There is **no** `ms_played`, no album field, no `reason_start`/`reason_end`, no
`shuffle`/`skipped`/`offline`/`incognito`, and no stable track URI. That absence
is what drives the gaps below.

### Field-mapping table

| Takeout field | `YouTubeMusicRecord` attr | Canonical `Event` field | Notes |
|---|---|---|---|
| `time` | `time: datetime` | `t_utc` | Direct; pydantic parses ISO-8601. Play **start** (no end). |
| `title` | `title: str \| None` | → `content` (via `content_line()`) | Opaque display text; verb prefix is locale-bound, not parsed. |
| `subtitles[0].name` | `channel: str \| None` | → `content` | Artist-ish; may be `"X - Topic"`. Not a clean artist. |
| `titleUrl` | `title_url: str \| None` | → `video_id`, `raw_ref` | `v=` param is the videoId; absent for deleted/private items. |
| `header` | `header: str \| None` | (filter only) | `"YouTube Music"` ⇒ keep as a music play. |
| `products` | `products: list[str]` | (filter fallback) | Weaker signal than `header`. |
| — | `video_id` (derived) | → `raw_ref`, `event_id()` | Parsed from `title_url`. |
| (constant) | — | `author_role = "self"` | A play is the user's own action, as with Spotify. |
| (constant) | `YT_MUSIC_THREAD_ID` | `thread_id` | One listening timeline; mirrors `SPOTIFY_THREAD_ID`. |
| (none) | — | `reply_to = None` | No reply concept, same as Spotify. |
| (constant) | — | `source = "youtube_music"` | New source tag in the unified table. |

### `raw_ref`, `event_id`, `content_line`, `thread_id`, filtering

- **`raw_ref`** — mirror Spotify's `uri#ts` convention with a videoId-based
  pointer plus the timestamp to disambiguate repeat plays of the same video:
  `"yt:video:<videoId>#<time.isoformat()>"`. When `titleUrl` is missing we fall
  back to the `title` text (prefixed `yt:title:`), the same way Spotify falls back
  to `display_title` when no URI exists. `raw_ref` is the "jump to original" link;
  for YouTube it resolves to `https://www.youtube.com/watch?v=<videoId>`.
- **`event_id()`** — identical recipe to Spotify:
  `sha256(raw_ref)[:16]`. Idempotent on re-import, so `add_events`
  (`INSERT OR REPLACE`) stays safe. Because `raw_ref` already includes `time`, the
  same play yields the same id every run.
- **`content_line()`** — the human line that reaches Hindsight. Without a clean
  artist/album split, the best we can do is, e.g.,
  `"Listened to '<title>' on <channel>"`, dropping the album clause entirely
  (we have no album). Compare Spotify's
  `"Listened to 'Track' by Artist (album Album)"` — strictly less structured.
- **`thread_id`** — a single constant `YT_MUSIC_THREAD_ID = "youtube_music:listening"`,
  exactly mirroring `SPOTIFY_THREAD_ID` so the episode gap-windowing collapses
  consecutive plays into listening sessions.
- **Filtering (music vs. video).** This is the new concern with no Spotify analog.
  The adapter's projector keeps a record only when it is a music play:
  primarily `header == "YouTube Music"`; if `header` is missing/ambiguous, fall
  back to a `products`/channel heuristic (e.g. channel ends with `" - Topic"`).
  This replaces Spotify's `min_ms_played` predicate as the adapter's filter step —
  same place in the pipeline (`records_to_events`), different predicate.

---

## Gaps & lossiness

Concrete, honest list of what does not survive the swap:

- **No `ms_played` → no duration, no skip-filter.** Spotify drops plays shorter
  than `DEFAULT_MIN_MS_PLAYED` (30 s) as noise; Takeout has **no duration field at
  all**, so that filter has no analog. Options, none great: (a) keep every Music
  entry (accept more noise); (b) approximate "engagement" by gaps between
  consecutive `time` values within a session (very rough, and a long gap could
  just mean the user stopped); (c) drop nothing and lean on the music-vs-video
  filter as the only noise gate. Recommendation: **(c)** — filter on `header`,
  don't pretend to infer duration.
- **No clean artist/album.** Spotify gives `master_metadata_album_artist_name`
  and `master_metadata_album_album_name` as discrete fields. Takeout gives a
  channel name (often `"<Artist> - Topic"`) and a free-text `title`. We can
  *heuristically* strip the `" - Topic"` suffix to guess an artist, but there is
  **no album signal at all**, and the artist guess is unreliable for non-Topic
  channels (covers, live sets, user uploads). `content_line()` is therefore
  flatter than Spotify's.
- **Video-vs-music disambiguation is heuristic, not guaranteed.** `header` is the
  best discriminator but is not contractually stable across Takeout versions, and
  ordinary music videos watched on plain YouTube (not Music) will carry
  `header == "YouTube"` and be excluded even though they *are* music listens. We
  will both over- and under-count relative to true listening.
- **No `shuffle` / `skipped` / `reason_start` / `reason_end` / `offline` /
  `incognito`.** None of Spotify's playback-context signals exist in Takeout. Any
  downstream feature that keyed on "did the user skip this" or "was this
  shuffled" simply cannot be built from this source.
- **Dedup key differs.** Spotify dedups on `track_uri#ts`; we dedup on
  `videoId#time`. Two practical wrinkles: (1) the *same* song often has multiple
  videoIds (official video, Topic auto-track, lyric video, re-uploads), so the
  same listen does not collapse the way Spotify's stable `spotify:track:` URI
  does; (2) deleted/private items lose `titleUrl`, forcing the `title`-text
  fallback, which is weaker and locale-sensitive. So cross-play identity is
  noisier than Spotify's.
- **`time` semantics differ subtly.** Spotify's `ts` is play *end*; Takeout's
  `time` is the event start/occurrence. Episode windowing still works (it only
  needs a monotonic timestamp per event), but any logic that assumed "ts = when
  the track finished" would be off by roughly one track length.

---

## Proposed model sketch

Illustrative, matching our existing docstring/style conventions in
[`models/spotify.py`](../src/models/spotify.py). Not necessarily runnable.

```python
"""Pydantic model for a single Google Takeout YouTube Music play.

Source: ``Takeout/YouTube and YouTube Music/history/watch-history.json`` — one
JSON array of activity records. YouTube Music plays are interleaved with ordinary
YouTube video views in the same file; ``header == "YouTube Music"`` is the
primary discriminator (see the adapter's filter).

Mirrors :mod:`models.spotify`: a typed source record that projects itself onto
the canonical :class:`~recall.schema.Event` via :meth:`to_event`, so YouTube
Music rides the same store -> episodes -> Hindsight pipeline as every source.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field

from recall.schema import Event

#: thread_id all YT Music plays share, so episode gap-windowing collapses
#: consecutive plays into listening sessions (one timeline). Mirrors
#: ``SPOTIFY_THREAD_ID``.
YT_MUSIC_THREAD_ID = "youtube_music:listening"


class _Subtitle(BaseModel):
    """A Takeout ``subtitles[]`` entry: the channel (artist-ish) for the item."""

    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    url: str | None = None


class YouTubeMusicRecord(BaseModel):
    """One watch-history record: a single YouTube Music play.

    Validates a raw Takeout record directly (``model_validate(record)``). Every
    field is optional because Takeout omits ``titleUrl`` / ``subtitles`` on
    deleted or private items.
    """

    model_config = ConfigDict(extra="ignore")

    #: Surface the activity came from; "YouTube Music" for music plays.
    header: str | None = None
    #: Free-text display label, e.g. "Watched <title>". Verb prefix is locale
    #: dependent, so we treat this as opaque text, not a parseable structure.
    title: str | None = None
    #: Watch URL; its ``v=`` param is the only stable per-item id (videoId).
    title_url: str | None = Field(default=None, alias="titleUrl")
    #: Channel entries; ``subtitles[0].name`` is the closest thing to an artist.
    subtitles: list[_Subtitle] = Field(default_factory=list)
    #: ISO-8601 UTC; the play *start*/occurrence time (no end time exists).
    time: datetime
    #: Coarse product tags; weaker music signal than ``header``.
    products: list[str] = Field(default_factory=list)

    @property
    def is_music(self) -> bool:
        """Whether this record is a YT Music play (vs. a plain video view)."""
        return self.header == "YouTube Music"

    @property
    def channel(self) -> str | None:
        """Channel name (artist-ish), from the first subtitle if present."""
        return self.subtitles[0].name if self.subtitles else None

    @property
    def video_id(self) -> str | None:
        """videoId parsed from ``title_url`` (``None`` if absent)."""
        if not self.title_url:
            return None
        return (parse_qs(urlparse(self.title_url).query).get("v") or [None])[0]

    @property
    def raw_ref(self) -> str:
        """Pointer back to the source play: videoId (or title) plus its ``time``.

        Mirrors Spotify's ``uri#ts`` convention; ``time`` disambiguates repeat
        plays of the same video. Falls back to the title text when ``title_url``
        is missing (deleted/private item).
        """
        if self.video_id:
            ref = f"yt:video:{self.video_id}"
        else:
            ref = f"yt:title:{self.title or 'unknown'}"
        return f"{ref}#{self.time.isoformat()}"

    def event_id(self) -> str:
        """Deterministic, idempotent id derived from :attr:`raw_ref`."""
        return hashlib.sha256(self.raw_ref.encode("utf-8")).hexdigest()[:16]

    def content_line(self) -> str:
        """Render the play as a readable line for the canonical ``Event``.

        Flatter than Spotify's: no album signal exists, and the channel is only
        an approximate artist (often "<Artist> - Topic").
        """
        title = self.title or "unknown title"
        chan = self.channel
        return f"Listened to '{title}'" + (f" on {chan}" if chan else "")

    def to_event(self) -> Event:
        """Project this play onto the canonical :class:`~recall.schema.Event`.

        The seam that puts YouTube Music on the shared provenance path: the event
        flows through ``store.add_events`` (durable ``events`` table +
        ``content_sha``), ``build_episodes``, and Hindsight ``retain`` unchanged.
        ``author_role`` is always "self" — a play is the user's own action.
        """
        return Event(
            id=self.event_id(),
            t_utc=self.time,
            author_role="self",
            content=self.content_line(),
            thread_id=YT_MUSIC_THREAD_ID,
            reply_to=None,
            raw_ref=self.raw_ref,
            source="youtube_music",
        )
```

The adapter (`adaptors/youtube_music.py`) is then a near-copy of
[`adaptors/spotify.py`](../src/adaptors/spotify.py): `read_records()` loads the
one `watch-history.json` array and validates each dict; `records_to_events()`
projects only `is_music` records (the filter step that replaces `min_ms_played`);
`ingest()` composes them; `main()` writes JSONL and calls `persist_events`.

---

## Open questions

- **HTML vs. JSON Takeout.** Takeout defaults to **HTML** for YouTube history; the
  user must explicitly switch the format to JSON. If we can't rely on users
  choosing JSON, we'd need an HTML parser (BeautifulSoup over the
  `outer-cell`/`content-cell` div structure) — strictly worse and brittle. Open:
  do we mandate JSON in our instructions, or support both?
- **Is YT Music history truly separable from YouTube watch history?** As far as we
  know there is **one** `watch-history.json` with both interleaved, separated only
  by the `header` string. We have not confirmed `header == "YouTube Music"` is
  emitted consistently across all locales/Takeout versions, nor that it never
  appears on non-music content. Needs validation against a real export before we
  trust the filter.
- **`products` reliability.** We are unsure whether `products` ever distinguishes
  Music from video (it often just says `["YouTube"]` for both). Until verified, we
  treat `header` as authoritative and `products` as a soft fallback only.
- **Same-song multiple videoIds.** Should we attempt cross-videoId song identity
  (official video vs. Topic track vs. lyric video collapsing to one song)? That
  needs an external lookup (e.g. the YouTube Data API or MusicBrainz) and is out
  of scope for a Takeout-only adapter — but it caps how good dedup/analytics can
  get.
- **Why not the YouTube Data / YT Music APIs instead?** They'd give cleaner,
  structured metadata, but: the official YouTube Data API does **not** expose a
  user's full personal listening history (watch history was removed from the API
  years ago), and unofficial YT Music endpoints are unauthenticated-scraping,
  brittle, and ToS-risky. Takeout is the only first-party, complete-history,
  non-scraping route — so we accept its lossiness rather than depend on an API
  that can't actually return the data.
