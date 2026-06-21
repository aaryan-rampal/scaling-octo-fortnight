"""Fixture-only tests for rung-③ minting (cluster-first).

No network and no real Hindsight: the LLM seam is a fake ``PrincipleProposer``
and embeddings are tiny hand-built vectors. These tests pin the deterministic
grounding guarantees — clustering, the ledger confidence formula, citation
verification, the novelty check, and the >=2-supports gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.principle import LedgerRow, Principle
from pipeline.mint import (
    MemoryCard,
    cluster_memories,
    compute_confidence,
    is_novel,
    mint_principles,
    verify_citations,
)


def _card(mid: str, emb: list[float] | None, *, source: str = "imessage", ts: str | None = None):
    return MemoryCard(
        memory_id=mid,
        text=f"memory {mid}",
        source=source,
        ts=ts or "2026-06-14T12:00:00+00:00",
        embedding=emb,
    )


def _row(mid: str, stance: str, *, source: str = "imessage", ts: str = "2026-06-14T12:00:00+00:00"):
    return LedgerRow(memory_id=mid, stance=stance, source=source, quote="q", ts=ts)


# --- clustering ------------------------------------------------------------------


def test_cluster_groups_similar_and_drops_singletons() -> None:
    near_a = _card("a1", [1.0, 0.0])
    near_b = _card("a2", [0.99, 0.01])  # ~same direction as a1 -> same cluster
    lone = _card("b1", [0.0, 1.0])  # orthogonal -> singleton, dropped
    clusters = cluster_memories([near_a, near_b, lone], threshold=0.9)
    assert len(clusters) == 1
    assert {m.memory_id for m in clusters[0]} == {"a1", "a2"}


def test_cluster_skips_cards_without_embedding() -> None:
    a = _card("a", [1.0, 0.0])
    b = _card("b", [1.0, 0.0])
    no_emb = _card("c", None)
    clusters = cluster_memories([a, b, no_emb], threshold=0.9)
    assert {m.memory_id for c in clusters for m in c} == {"a", "b"}


# --- confidence ------------------------------------------------------------------


def test_confidence_thin_evidence_is_humble() -> None:
    now = datetime(2026, 6, 14, 12, tzinfo=UTC)
    # 2 supports, same source, fresh (recency ~1), no contradictions.
    ledger = [_row("m1", "supports"), _row("m2", "supports")]
    conf = compute_confidence(ledger, now=now)
    # raw = 2 + 0.5*1 + 1 = 3.5 ; denom = 2 + 3 = 5 -> 0.7 ... still bounded, not 1.0
    assert 0.0 < conf < 1.0


def test_confidence_contradiction_counts_double_against() -> None:
    now = datetime(2026, 6, 14, 12, tzinfo=UTC)
    base = [_row("m1", "supports"), _row("m2", "supports")]
    with_contra = [*base, _row("m3", "contradicts")]
    assert compute_confidence(with_contra, now=now) < compute_confidence(base, now=now)


def test_confidence_source_diversity_lifts() -> None:
    now = datetime(2026, 6, 14, 12, tzinfo=UTC)
    same = [_row("m1", "supports", source="imessage"), _row("m2", "supports", source="imessage")]
    diverse = [_row("m1", "supports", source="imessage"), _row("m2", "supports", source="photos")]
    assert compute_confidence(diverse, now=now) > compute_confidence(same, now=now)


def test_confidence_decays_as_supports_age() -> None:
    now = datetime(2026, 7, 14, 12, tzinfo=UTC)  # 30d after the memories
    fresh = [
        _row("m1", "supports", ts="2026-07-14T12:00:00+00:00"),
        _row("m2", "supports", ts="2026-07-14T12:00:00+00:00"),
    ]
    old = [
        _row("m1", "supports", ts="2026-06-14T12:00:00+00:00"),
        _row("m2", "supports", ts="2026-06-14T12:00:00+00:00"),
    ]
    assert compute_confidence(fresh, now=now) > compute_confidence(old, now=now)


def test_confidence_always_in_unit_range() -> None:
    now = datetime(2026, 6, 14, 12, tzinfo=UTC)
    many_contra = [_row(f"c{i}", "contradicts") for i in range(10)]
    assert compute_confidence(many_contra, now=now) == 0.0


# --- citation verification -------------------------------------------------------


def test_verify_citations_drops_ids_outside_cluster() -> None:
    cluster = [_card("a", [1.0]), _card("b", [1.0])]
    kept = verify_citations(["a", "ghost", "b"], cluster)
    assert kept == ["a", "b"]


# --- novelty ---------------------------------------------------------------------


def test_is_novel_rejects_restatement_of_single_memory() -> None:
    cited = [_card("a", [1.0, 0.0]), _card("b", [0.0, 1.0])]
    # Principle vector identical to memory a -> cosine 1.0 -> not novel.
    assert is_novel([1.0, 0.0], cited) is False


def test_is_novel_accepts_synthesis() -> None:
    cited = [_card("a", [1.0, 0.0]), _card("b", [0.0, 1.0])]
    # A blend of both, not equal to either -> novel.
    assert is_novel([0.7, 0.7], cited) is True


# --- full pass -------------------------------------------------------------------


class _FakeProposer:
    """Returns a fixed candidate per cluster, citing the cluster's first two ids."""

    def __init__(self, text: str, *, cite_ghost: bool = False) -> None:
        self.text = text
        self.cite_ghost = cite_ghost

    def propose(self, cards: list[MemoryCard]) -> list[tuple[str, list[str]]]:
        ids = [m.memory_id for m in cards[:2]]
        if self.cite_ghost:
            ids = [ids[0], "ghost"]  # one valid, one invented -> fails >=2 gate
        return [(self.text, ids)]


def _embed_orthogonal(_text: str) -> list[float]:
    """Principle embedding far from the memory vectors (passes novelty)."""
    return [0.0, 0.0, 1.0]


def test_mint_principles_emits_grounded_principle() -> None:
    cards = [_card("a", [1.0, 0.0, 0.0]), _card("b", [0.98, 0.02, 0.0])]
    out = mint_principles(
        cards, _FakeProposer("keep weekends free"), _embed_orthogonal, threshold=0.9
    )
    assert len(out) == 1
    p = out[0]
    assert isinstance(p, Principle)
    assert p.text == "keep weekends free"
    assert set(p.derived_from) == {"a", "b"}
    assert 0.0 <= p.confidence <= 1.0


def test_mint_principles_rejects_when_citations_fail_gate() -> None:
    cards = [_card("a", [1.0, 0.0, 0.0]), _card("b", [0.98, 0.02, 0.0])]
    out = mint_principles(
        cards, _FakeProposer("x", cite_ghost=True), _embed_orthogonal, threshold=0.9
    )
    assert out == []


def test_mint_principles_rejects_restatement() -> None:
    cards = [_card("a", [1.0, 0.0, 0.0]), _card("b", [0.98, 0.02, 0.0])]
    # Principle embeds identical to memory a -> novelty rejects it.
    out = mint_principles(cards, _FakeProposer("x"), lambda _t: [1.0, 0.0, 0.0], threshold=0.9)
    assert out == []


def test_principle_node_enforces_two_supports() -> None:
    with pytest.raises(ValueError, match=">=2 distinct"):
        Principle(principle_id="p", text="t", confidence=0.5, derived_from=["only-one"])
