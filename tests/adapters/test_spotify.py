"""Tests for the Spotify model + adapter against a synthetic export fixture."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.spotify import (
    enrich_records,
    ingest,
    load_vibe_cache,
    read_records,
    records_to_events,
    resolve_vibes,
)
from models.spotify import SPOTIFY_THREAD_ID, SpotifyStreamRecord
from pipeline.episodes import build_episodes
from storage.store import CapsuleStore

# A real-shaped music record from the Extended Streaming History export.
_MUSIC = {
    "ts": "2024-03-01T12:00:00Z",
    "platform": "osx",
    "ms_played": 200000,
    "conn_country": "US",
    "master_metadata_track_name": "Pasoori",
    "master_metadata_album_artist_name": "Shae Gill",
    "master_metadata_album_album_name": "Pasoori",
    "spotify_track_uri": "spotify:track:7lvDsmTRXFE3dK4OjvRiWB",
    "episode_name": None,
    "spotify_episode_uri": None,
    "reason_start": "trackdone",
    "reason_end": "trackdone",
    "shuffle": False,
    "skipped": False,
}

_PODCAST = {
    "ts": "2024-03-01T13:00:00Z",
    "ms_played": 600000,
    "master_metadata_track_name": None,
    "episode_name": "Episode 42",
    "episode_show_name": "Some Show",
    "spotify_episode_uri": "spotify:episode:abc123",
}

_SHORT_SKIP = {
    "ts": "2024-03-01T12:05:00Z",
    "ms_played": 1500,  # below the default min, should be dropped
    "master_metadata_track_name": "Skipped",
    "master_metadata_album_artist_name": "Nobody",
    "spotify_track_uri": "spotify:track:skipped",
}


def test_model_validates_by_alias_and_classifies() -> None:
    rec = SpotifyStreamRecord.model_validate(_MUSIC)
    assert rec.kind == "music"
    assert rec.track_name == "Pasoori"
    assert rec.artist_name == "Shae Gill"
    assert rec.track_id == "7lvDsmTRXFE3dK4OjvRiWB"

    pod = SpotifyStreamRecord.model_validate(_PODCAST)
    assert pod.kind == "podcast"
    assert pod.display_title == "Episode 42"


def test_to_event_lands_on_canonical_event() -> None:
    event = SpotifyStreamRecord.model_validate(_MUSIC).to_event()
    assert event.source == "spotify"
    assert event.author_role == "self"
    assert event.thread_id == SPOTIFY_THREAD_ID
    assert event.content is not None
    assert "Pasoori" in event.content and "Shae Gill" in event.content
    # raw_ref points back to the play, with no doubled prefix.
    assert event.raw_ref.startswith("spotify:track:7lvDsmTRXFE3dK4OjvRiWB#")
    assert "spotify:spotify:" not in event.raw_ref


def test_event_id_is_deterministic_and_unique_per_play() -> None:
    a = SpotifyStreamRecord.model_validate(_MUSIC).to_event()
    b = SpotifyStreamRecord.model_validate(_MUSIC).to_event()
    assert a.id == b.id  # same play -> same id (idempotent re-import)
    other = dict(_MUSIC, ts="2024-03-02T12:00:00Z")
    assert SpotifyStreamRecord.model_validate(other).to_event().id != a.id


def _write_export(tmp_path: Path, records: list[dict]) -> Path:
    folder = tmp_path / "Spotify Extended Streaming History"
    folder.mkdir()
    (folder / "Streaming_History_Audio_2024.json").write_text(json.dumps(records), encoding="utf-8")
    return tmp_path


def test_read_records_walks_export_folder(tmp_path: Path) -> None:
    root = _write_export(tmp_path, [_MUSIC, _PODCAST])
    records = list(read_records(root))
    assert len(records) == 2
    # also accepts the inner folder directly
    assert len(list(read_records(root / "Spotify Extended Streaming History"))) == 2


def test_ingest_filters_short_plays_and_feeds_pipeline(tmp_path: Path) -> None:
    root = _write_export(tmp_path, [_MUSIC, _PODCAST, _SHORT_SKIP])
    events = ingest(root)
    assert len(events) == 2  # the short skip is dropped by default

    # keep-all override
    assert len(records_to_events(read_records(root), min_ms_played=0)) == 3

    # provenance path: persists into the shared events table with integrity hash
    store = CapsuleStore(":memory:")
    assert store.add_events(events) == 2
    assert store.verify_event(events[0].id) is True
    assert len(store.list_events(source="spotify")) == 2

    # windowing works on plays (no source-specific handling)
    assert len(build_episodes(events)) >= 1


def _stub_resolver(calls: list[str]):
    """Resolver that records each artist it is asked about (no network)."""

    def resolve(artist: str) -> str:
        calls.append(artist)
        return f"vibe-of-{artist}"

    return resolve


def test_resolve_vibes_calls_resolver_once_per_unique_artist() -> None:
    calls: list[str] = []
    vibes = resolve_vibes(
        ["Calvin Harris", "Kesha", "Calvin Harris"],
        cache={},
        resolver=_stub_resolver(calls),
    )
    assert vibes == {"Calvin Harris": "vibe-of-Calvin Harris", "Kesha": "vibe-of-Kesha"}
    assert sorted(calls) == ["Calvin Harris", "Kesha"]  # dedup: Calvin once


def test_resolve_vibes_never_recalls_cached_artist() -> None:
    calls: list[str] = []
    cache = {"Calvin Harris": "high-energy EDM/pop"}
    resolve_vibes(["Calvin Harris"], cache=cache, resolver=_stub_resolver(calls))
    assert calls == []  # cache hit -> no resolver call


def test_enrich_records_stamps_vibe_and_persists_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "artist_vibes.json"
    calls: list[str] = []
    records = [SpotifyStreamRecord.model_validate(_MUSIC)]
    enrich_records(records, cache_path=cache_path, resolver=_stub_resolver(calls))

    # vibe lands on the record, the event content, and additional_data
    assert records[0].artist_vibe == "vibe-of-Shae Gill"
    event = records[0].to_event()
    assert event.additional_data["artist_vibe"] == "vibe-of-Shae Gill"
    assert "(vibe-of-Shae Gill)" in (event.content or "")

    # cache is written and reusable -> a second pass makes no calls
    assert load_vibe_cache(cache_path) == {"Shae Gill": "vibe-of-Shae Gill"}
    calls.clear()
    enrich_records(
        [SpotifyStreamRecord.model_validate(_MUSIC)],
        cache_path=cache_path,
        resolver=_stub_resolver(calls),
    )
    assert calls == []


def test_load_vibe_cache_tolerates_corrupt_file(tmp_path: Path) -> None:
    # A truncated/invalid cache must degrade to {}, not crash the ingest.
    truncated = tmp_path / "truncated.json"
    truncated.write_text('{"Artist": "vibe",')  # invalid JSON
    assert load_vibe_cache(truncated) == {}
    not_a_dict = tmp_path / "list.json"
    not_a_dict.write_text("[1, 2, 3]")  # valid JSON, wrong shape
    assert load_vibe_cache(not_a_dict) == {}


def test_enrich_records_ignores_non_music(tmp_path: Path) -> None:
    calls: list[str] = []
    records = [SpotifyStreamRecord.model_validate(_PODCAST)]
    enrich_records(records, cache_path=tmp_path / "c.json", resolver=_stub_resolver(calls))
    assert records[0].artist_vibe is None
    assert calls == []


def test_ingest_enrich_flag_threads_vibe_into_events(tmp_path: Path) -> None:
    root = _write_export(tmp_path, [_MUSIC, _PODCAST])
    calls: list[str] = []
    events = ingest(
        root,
        enrich=True,
        cache_path=tmp_path / "vibes.json",
        resolver=_stub_resolver(calls),
    )
    music = next(e for e in events if "Pasoori" in (e.content or ""))
    assert music.additional_data["artist_vibe"] == "vibe-of-Shae Gill"
    assert calls == ["Shae Gill"]


def test_ingest_without_enrich_has_no_vibe(tmp_path: Path) -> None:
    root = _write_export(tmp_path, [_MUSIC])
    events = ingest(root)
    assert "artist_vibe" not in events[0].additional_data
