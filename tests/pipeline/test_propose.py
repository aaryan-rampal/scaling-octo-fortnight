"""Fixture-only tests for pipeline.propose.

No network, no pg0, no LLM. All external seams are faked so these tests run
offline and never spend money. Coverage targets:

- ``recall_to_cards``: tag→source derivation, occurred_start→ts, dedup by id,
  embedding join from a fake pg reader.
- ``_parse_proposals``: clean JSON, markdown-fenced JSON, malformed JSON,
  missing fields — all handled defensively.
- ``LLMProposer.propose``: happy-path parsing and error resilience (bad JSON).
- Runner wiring: that ``_run_with_observability`` calls ``mint_cluster`` with
  the right proposer and embedder, producing principle dicts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from pipeline.mint import MemoryCard
from pipeline.propose import (
    LLMProposer,
    _parse_proposals,
    _source_from_tags,
    _ts_from_occurred,
    recall_to_cards,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_recall_result(
    mid: str,
    text: str,
    tags: list[str],
    occurred_start: Any = None,
) -> MagicMock:
    r = MagicMock()
    r.id = mid
    r.text = text
    r.tags = tags
    r.occurred_start = occurred_start
    return r


class _FakePgReader:
    """Fake PgVectorReader that returns canned embeddings."""

    def __init__(self, embeddings: dict[str, list[float]]) -> None:
        self._embeddings = embeddings

    def read(self, memory_ids: list[str]) -> dict[str, list[float]]:
        return {mid: self._embeddings[mid] for mid in memory_ids if mid in self._embeddings}

    def close(self) -> None:
        pass

    def __enter__(self) -> _FakePgReader:
        return self

    def __exit__(self, *_: object) -> None:
        pass


class _FakeClient:
    """Fake Hindsight client whose recall() returns canned results."""

    def __init__(self, results: list[MagicMock]) -> None:
        self._results = results

    def recall(self, **kwargs: Any) -> list[MagicMock]:
        return self._results


# ---------------------------------------------------------------------------
# _source_from_tags
# ---------------------------------------------------------------------------


def test_source_from_tags_picks_known_source() -> None:
    assert _source_from_tags(["network:experience", "imessage", "author:self"]) == "imessage"


def test_source_from_tags_returns_unknown_when_none_match() -> None:
    assert _source_from_tags(["network:world", "author:other"]) == "unknown"


def test_source_from_tags_picks_first_known() -> None:
    # When two known sources appear, first in list wins.
    assert _source_from_tags(["photos", "spotify"]) == "photos"


# ---------------------------------------------------------------------------
# _ts_from_occurred
# ---------------------------------------------------------------------------


def test_ts_from_occurred_handles_datetime() -> None:
    dt = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    ts = _ts_from_occurred(dt)
    assert "2026-06-14" in ts


def test_ts_from_occurred_handles_string() -> None:
    assert _ts_from_occurred("2026-06-14T12:00:00+00:00") == "2026-06-14T12:00:00+00:00"


def test_ts_from_occurred_handles_none() -> None:
    assert _ts_from_occurred(None) == ""


# ---------------------------------------------------------------------------
# recall_to_cards — mapping and dedup
# ---------------------------------------------------------------------------


def test_recall_to_cards_maps_tag_to_source() -> None:
    r1 = _fake_recall_result("id1", "went hiking", ["imessage", "author:self"])
    r2 = _fake_recall_result("id2", "listened to music", ["spotify", "author:self"])
    client = _FakeClient([r1, r2])
    pg = _FakePgReader({"id1": [1.0, 0.0], "id2": [0.0, 1.0]})

    cards = recall_to_cards(client, "query", "bank", pg_reader=pg)

    by_id = {c.memory_id: c for c in cards}
    assert by_id["id1"].source == "imessage"
    assert by_id["id2"].source == "spotify"


def test_recall_to_cards_joins_embedding() -> None:
    r1 = _fake_recall_result("id1", "text", ["imessage"])
    client = _FakeClient([r1])
    pg = _FakePgReader({"id1": [0.5, 0.5]})

    cards = recall_to_cards(client, "q", "bank", pg_reader=pg)
    assert cards[0].embedding == [0.5, 0.5]


def test_recall_to_cards_missing_embedding_is_none() -> None:
    r1 = _fake_recall_result("id1", "text", ["imessage"])
    client = _FakeClient([r1])
    pg = _FakePgReader({})  # no embedding stored

    cards = recall_to_cards(client, "q", "bank", pg_reader=pg)
    assert cards[0].embedding is None


def test_recall_to_cards_deduplicates_by_id() -> None:
    # Same id appearing twice (e.g. from two types) → only one card.
    r1 = _fake_recall_result("same", "text a", ["imessage"])
    r2 = _fake_recall_result("same", "text b", ["imessage"])
    client = _FakeClient([r1, r2])
    pg = _FakePgReader({})

    cards = recall_to_cards(client, "q", "bank", pg_reader=pg)
    assert len(cards) == 1
    assert cards[0].memory_id == "same"


def test_recall_to_cards_ts_from_occurred_start() -> None:
    dt = datetime(2026, 1, 1, tzinfo=UTC)
    r1 = _fake_recall_result("id1", "text", ["imessage"], occurred_start=dt)
    client = _FakeClient([r1])
    pg = _FakePgReader({})

    cards = recall_to_cards(client, "q", "bank", pg_reader=pg)
    assert "2026-01-01" in cards[0].ts


# ---------------------------------------------------------------------------
# _parse_proposals — defensive JSON parsing
# ---------------------------------------------------------------------------


def test_parse_proposals_clean_json() -> None:
    raw = '[{"text": "You value friends", "memory_ids": ["a", "b"]}]'
    result = _parse_proposals(raw)
    assert result == [("You value friends", ["a", "b"])]


def test_parse_proposals_strips_markdown_fences() -> None:
    raw = '```json\n[{"text": "You sleep late", "memory_ids": ["x", "y"]}]\n```'
    result = _parse_proposals(raw)
    assert len(result) == 1
    assert result[0][0] == "You sleep late"


def test_parse_proposals_multiple_entries() -> None:
    raw = '[{"text": "P1", "memory_ids": ["a", "b"]}, {"text": "P2", "memory_ids": ["c", "d"]}]'
    result = _parse_proposals(raw)
    assert len(result) == 2


def test_parse_proposals_drops_entry_missing_text() -> None:
    raw = '[{"memory_ids": ["a", "b"]}, {"text": "Valid", "memory_ids": ["a", "b"]}]'
    result = _parse_proposals(raw)
    assert len(result) == 1
    assert result[0][0] == "Valid"


def test_parse_proposals_drops_entry_missing_ids() -> None:
    raw = '[{"text": "No ids"}]'
    result = _parse_proposals(raw)
    assert result == []


def test_parse_proposals_returns_empty_on_malformed_json() -> None:
    result = _parse_proposals("this is not json at all")
    assert result == []


def test_parse_proposals_returns_empty_on_empty_array() -> None:
    result = _parse_proposals("[]")
    assert result == []


# ---------------------------------------------------------------------------
# LLMProposer — wiring (fake OpenAI client)
# ---------------------------------------------------------------------------


def _make_fake_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_llm_proposer_parses_valid_response() -> None:
    raw = '[{"text": "You value quality time", "memory_ids": ["m1", "m2"]}]'
    fake_oai = MagicMock()
    fake_oai.chat.completions.create.return_value = _make_fake_completion(raw)

    with patch("pipeline.propose.OpenAI", return_value=fake_oai):
        proposer = LLMProposer(api_key="fake-key")

    cards = [
        MemoryCard("m1", "text a", "imessage", "2026-01-01", [1.0, 0.0]),
        MemoryCard("m2", "text b", "imessage", "2026-01-02", [0.9, 0.1]),
    ]
    result = proposer.propose(cards)
    assert result == [("You value quality time", ["m1", "m2"])]


def test_llm_proposer_returns_empty_on_bad_json() -> None:
    fake_oai = MagicMock()
    fake_oai.chat.completions.create.return_value = _make_fake_completion("not json")

    with patch("pipeline.propose.OpenAI", return_value=fake_oai):
        proposer = LLMProposer(api_key="fake-key")

    cards = [
        MemoryCard("m1", "text a", "imessage", "2026-01-01", [1.0, 0.0]),
        MemoryCard("m2", "text b", "imessage", "2026-01-02", [0.9, 0.1]),
    ]
    result = proposer.propose(cards)
    assert result == []


def test_llm_proposer_returns_empty_on_api_error() -> None:
    fake_oai = MagicMock()
    fake_oai.chat.completions.create.side_effect = RuntimeError("network down")

    with patch("pipeline.propose.OpenAI", return_value=fake_oai):
        proposer = LLMProposer(api_key="fake-key")

    cards = [MemoryCard("m1", "text", "imessage", "2026-01-01", [1.0, 0.0])]
    result = proposer.propose(cards)
    assert result == []


# ---------------------------------------------------------------------------
# Runner wiring — _run_with_observability calls mint_cluster correctly
# ---------------------------------------------------------------------------


def test_run_with_observability_produces_principle_dicts() -> None:
    """End-to-end fixture test: cards → clusters → proposals → principle dicts."""
    from scripts.mint_principles import _run_with_observability  # type: ignore[import]

    cards = [
        MemoryCard("a", "memory a", "imessage", "2026-06-01T00:00:00+00:00", [1.0, 0.0, 0.0]),
        MemoryCard("b", "memory b", "imessage", "2026-06-02T00:00:00+00:00", [0.98, 0.02, 0.0]),
    ]

    class _FakeProposer:
        def propose(self, cluster: list[MemoryCard]) -> list[tuple[str, list[str]]]:
            return [("You keep weekends free", [c.memory_id for c in cluster[:2]])]

    class _FakeEmbedder:
        def embed(self, text: str) -> list[float]:
            return [0.0, 0.0, 1.0]  # orthogonal to memory vectors → novel

    result = _run_with_observability(
        cards,
        _FakeProposer(),  # type: ignore[arg-type]
        _FakeEmbedder(),  # type: ignore[arg-type]
        limit_clusters=0,
        dry_run=False,
    )
    assert len(result) == 1
    p = result[0]
    assert p["text"] == "You keep weekends free"
    assert set(p["derived_from"]) == {"a", "b"}
    assert 0.0 <= p["confidence"] <= 1.0
    assert isinstance(p["id"], str) and len(p["id"]) > 0


def test_run_with_observability_dry_run_skips_llm() -> None:
    from scripts.mint_principles import _run_with_observability  # type: ignore[import]

    cards = [
        MemoryCard("a", "text a", "imessage", "2026-06-01T00:00:00+00:00", [1.0, 0.0]),
        MemoryCard("b", "text b", "imessage", "2026-06-02T00:00:00+00:00", [0.98, 0.02]),
    ]

    class _TrackingProposer:
        called = False

        def propose(self, cluster: list[MemoryCard]) -> list[tuple[str, list[str]]]:
            _TrackingProposer.called = True
            return []

    class _FakeEmbedder:
        def embed(self, text: str) -> list[float]:
            return [0.0, 1.0]

    result = _run_with_observability(
        cards,
        _TrackingProposer(),  # type: ignore[arg-type]
        _FakeEmbedder(),  # type: ignore[arg-type]
        limit_clusters=0,
        dry_run=True,
    )
    assert result == []
    assert not _TrackingProposer.called
