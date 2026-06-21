"""Rung ③ — mint principles from the memory bank (cluster-first).

Reads the memory pile (Hindsight ``recall`` over the bank), groups related
memories into clusters, and proposes one-line :class:`~core.principle.Principle`
nodes — each backed by an evidence ledger of >=2 supporting ``memory_id``s and a
confidence derived from that ledger. The swarm and the contradiction flywheel are
out of scope (CLAUDE.md §3); this is a single manual consolidation pass.

The strategy is **cluster-first** (``docs/rung3-minting-strategy.md`` §5), chosen
for provenance fidelity: the LLM only ever sees one cluster, so every legal
citation is a member of a small, known set and a non-LLM script can reject any
``memory_id`` it did not see. The deterministic pieces here — clustering,
the ledger confidence formula, citation verification, the novelty check — carry
the grounding guarantees and are fully unit-testable; the one stochastic step
(proposing principle text + citing ids per cluster) sits behind the injectable
:class:`PrincipleProposer` protocol, mirroring rung ②'s ``RetainClient`` so tests
run without a network.

Two structural gates run before a principle is accepted, both checkable without
trusting LLM self-report (``docs/rung3-minting-strategy.md`` §4):

1. **>=2 distinct supporting ``memory_id``s** — singleton clusters never reach the
   LLM, and :class:`~core.principle.Principle` enforces the count at construction.
2. **Novelty** — the principle must not be a paraphrase of one cited memory
   (cosine similarity below :data:`NOVELTY_MAX_COSINE`).

Confidence is **never** the LLM's self-report — RLHF makes verbalized confidence
overconfident — but a monotone function of the ledger (count, source diversity,
recency, signed contradictions).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.principle import LedgerRow, Principle

#: Similarity at or above which two memories join the same cluster (cosine).
DEFAULT_CLUSTER_COSINE = 0.55

#: A principle whose embedding is at least this similar to a single cited memory
#: is rejected as a fluent restatement rather than genuine synthesis.
NOVELTY_MAX_COSINE = 0.9

#: Recency half-life (days) for weighting supporting memories in confidence.
RECENCY_HALFLIFE_DAYS = 30.0


@dataclass(frozen=True, slots=True)
class MemoryCard:
    """The slice of a Hindsight memory rung ③ reads — bank-snapshot shaped.

    Decoupled from Hindsight's wire type so mint stays pure and fixture-testable;
    a thin adapter maps a live ``recall`` result onto this later.

    Attributes:
        memory_id: Stable id of the memory (the citable unit).
        text: The memory's fact text.
        source: Originating source (``imessage`` / ``spotify`` / ``photos``);
            drives the source-diversity term in confidence.
        ts: ISO-8601 timestamp of the memory, for recency weighting.
        embedding: The memory's vector (Hindsight's own qwen embedding — we never
            re-embed). ``None`` when unavailable; such memories cannot cluster or
            be novelty-checked and are handled by the caller.
    """

    memory_id: str
    text: str
    source: str
    ts: str
    embedding: list[float] | None = None


class PrincipleProposer(Protocol):
    """The one stochastic seam: propose principle(s) for a single cluster.

    The implementation (live: an OpenRouter call; tests: a fake) is shown only the
    cluster's memories and must return candidate principles citing ``memory_id``s
    from that cluster. Returned citations are *not* trusted — :func:`mint_cluster`
    verifies every id against the cluster input set before anything is written.
    """

    def propose(self, cards: list[MemoryCard]) -> list[tuple[str, list[str]]]:
        """Return ``(principle_text, cited_memory_ids)`` candidates for the cluster."""
        ...


def _cosine(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of two equal-length vectors (0 if degenerate)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def cluster_memories(
    cards: list[MemoryCard], threshold: float = DEFAULT_CLUSTER_COSINE
) -> list[list[MemoryCard]]:
    """Group memories into clusters by embedding similarity; drop singletons.

    Deterministic single-link grouping: a card joins an existing cluster when its
    cosine similarity to any member is ``>= threshold``, else it starts a new one.
    Clusters of size 1 are dropped — they can never satisfy the >=2-supports gate,
    so rejecting them here saves an LLM call (``docs/rung3-minting-strategy.md`` §2).
    Cards without an embedding cannot be placed and are skipped.

    Args:
        cards: The recalled memories to cluster.
        threshold: Minimum cosine similarity to join a cluster.

    Returns:
        Clusters of >=2 memories each, in discovery order.
    """
    clusters: list[list[MemoryCard]] = []
    for card in cards:
        if card.embedding is None:
            continue
        placed = False
        for cluster in clusters:
            if any(
                m.embedding is not None and _cosine(card.embedding, m.embedding) >= threshold
                for m in cluster
            ):
                cluster.append(card)
                placed = True
                break
        if not placed:
            clusters.append([card])
    return [c for c in clusters if len(c) >= 2]


def _parse_ts(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, or ``None`` when blank/malformed.

    Memories from sources without a timestamp (e.g. standing ``world`` facts)
    carry an empty ``ts``; callers must tolerate that rather than crash.
    """
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_weight(ts: str, now: datetime, halflife_days: float) -> float:
    """Return ``0.5 ** (age_days / halflife)`` for a memory timestamp, clamped >=0."""
    when = _parse_ts(ts)
    if when is None:
        return 0.0
    age_days = max((now - when).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / halflife_days)


def compute_confidence(ledger: list[LedgerRow], *, now: datetime | None = None) -> float:
    """Confidence as a monotone function of the evidence ledger (never the LLM).

    Implements ``docs/rung3-minting-strategy.md`` §4:
    ``clip((S + 0.5*D + R - W - 2*C) / (S + W + 2*C + 3), 0, 1)`` where S/W/C are
    distinct supporting/weakening/contradicting ``memory_id`` counts, D is the
    number of distinct sources among supports (diversity), and R is the max
    recency weight over supports. Thin evidence stays humble (~0.4-0.5); a
    contradiction counts double against; diversity and recency lift it.

    Args:
        ledger: The principle's evidence rows.
        now: Reference time for recency (defaults to the latest ledger timestamp,
            so the formula is deterministic in tests without wall-clock coupling).

    Returns:
        Confidence in ``[0, 1]``.
    """
    supports = {r.memory_id for r in ledger if r.stance == "supports"}
    weakens = {r.memory_id for r in ledger if r.stance == "weakens"}
    contradicts = {r.memory_id for r in ledger if r.stance == "contradicts"}
    s, w, c = len(supports), len(weakens), len(contradicts)
    support_rows = [r for r in ledger if r.stance == "supports"]
    if now is None:
        parsed = [t for t in (_parse_ts(r.ts) for r in ledger) if t is not None]
        now = max(parsed, default=datetime.now().astimezone())
    diversity = len({r.source for r in support_rows})
    recency = max(
        (_recency_weight(r.ts, now, RECENCY_HALFLIFE_DAYS) for r in support_rows), default=0.0
    )
    raw = s + 0.5 * diversity + recency - w - 2 * c
    denom = s + w + 2 * c + 3
    return max(0.0, min(raw / denom, 1.0))


def verify_citations(cited: list[str], cluster: list[MemoryCard]) -> list[str]:
    """Keep only cited ids that are members of the cluster the LLM was shown.

    The non-LLM bound that makes cluster-first trustworthy: an id the model
    invented or mis-mapped is not in the cluster input set and is dropped, so a
    stored citation is guaranteed to have been in scope (``docs/rung3-minting-
    strategy.md`` §2). Order and duplicates of ``cited`` are preserved for the
    kept ids.

    Args:
        cited: ``memory_id``s the proposer returned for this cluster.
        cluster: The exact memories shown to the proposer.

    Returns:
        The subset of ``cited`` present in the cluster, in input order.
    """
    members = {m.memory_id for m in cluster}
    return [mid for mid in cited if mid in members]


def is_novel(
    principle_embedding: list[float],
    cited: list[MemoryCard],
    *,
    max_cosine: float = NOVELTY_MAX_COSINE,
) -> bool:
    """True if the principle is not a paraphrase of any single cited memory.

    Embeds nothing new: the principle vector is supplied by the caller, and cited
    memories carry their Hindsight embedding. A principle that is too similar to
    one memory (cosine ``>= max_cosine``) is a fluent restatement, not synthesis,
    and is rejected (``docs/rung3-minting-strategy.md`` §4).

    Args:
        principle_embedding: Vector for the proposed principle text.
        cited: The memories the principle cites.
        max_cosine: Rejection threshold.

    Returns:
        ``True`` when novel (below threshold against every cited memory).
    """
    for m in cited:
        if m.embedding is not None and _cosine(principle_embedding, m.embedding) >= max_cosine:
            return False
    return True


def build_ledger(cited: list[MemoryCard]) -> list[LedgerRow]:
    """Build a supports-only ledger from cited cluster memories.

    v0 treats every cited cluster member as a ``supports`` row (the proposer is
    asked for evidence *for* the principle). ``weakens`` / ``contradicts`` rows
    arrive later from the contradiction loop, which is out of scope here. The
    quote defaults to the memory text for display/audit.
    """
    return [
        LedgerRow(memory_id=m.memory_id, stance="supports", source=m.source, quote=m.text, ts=m.ts)
        for m in cited
    ]


@dataclass(frozen=True, slots=True)
class _Candidate:
    """An accepted (text, cited cards) pair, pre-confidence."""

    text: str
    cited: list[MemoryCard]


def mint_cluster(
    cluster: list[MemoryCard],
    proposer: PrincipleProposer,
    embed_principle: Any,
) -> list[_Candidate]:
    """Propose, verify, and novelty-filter principle candidates for one cluster.

    Runs the proposer over the cluster, then applies the non-LLM guards: every
    cited id must be a cluster member (>=2 surviving), and the principle must pass
    the novelty check against its cited memories. Confidence is *not* computed
    here — the caller does that once the (supports-only) ledger is built.

    Args:
        cluster: The >=2 memories shown to the proposer.
        proposer: The injectable LLM seam.
        embed_principle: Callable ``str -> list[float]`` for the novelty check
            (e.g. a thin wrapper over Hindsight's embedding endpoint).

    Returns:
        Accepted candidates (verified citations, novel). Empty if none survive.
    """
    by_id = {m.memory_id: m for m in cluster}
    accepted: list[_Candidate] = []
    for text, cited_ids in proposer.propose(cluster):
        verified = verify_citations(cited_ids, cluster)
        if len(set(verified)) < 2:
            continue
        cited_cards = [by_id[mid] for mid in dict.fromkeys(verified)]
        if not is_novel(embed_principle(text), cited_cards):
            continue
        accepted.append(_Candidate(text=text, cited=cited_cards))
    return accepted


def _principle_id(text: str, cited: list[MemoryCard]) -> str:
    """Stable id from the principle text and its sorted cited ids."""
    payload = "\x1f".join([text, *sorted(m.memory_id for m in cited)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def mint_principles(
    cards: list[MemoryCard],
    proposer: PrincipleProposer,
    embed_principle: Any,
    *,
    threshold: float = DEFAULT_CLUSTER_COSINE,
    now: datetime | None = None,
) -> list[Principle]:
    """Run the full cluster-first minting pass over a recalled memory pile.

    Clusters the memories, drops singletons, proposes principles per cluster,
    verifies citations and novelty, then computes ledger confidence — emitting a
    :class:`~core.principle.Principle` per accepted candidate. No principle is ever
    written without >=2 verified supports (enforced both here and in the node).

    Args:
        cards: The recalled memories (with Hindsight embeddings) to consolidate.
        proposer: The injectable LLM seam proposing text + citations per cluster.
        embed_principle: Callable ``str -> list[float]`` for the novelty check.
        threshold: Clustering cosine threshold.
        now: Reference time for recency weighting (see :func:`compute_confidence`).

    Returns:
        Minted principles, one per accepted candidate.
    """
    principles: list[Principle] = []
    for cluster in cluster_memories(cards, threshold):
        for cand in mint_cluster(cluster, proposer, embed_principle):
            ledger = build_ledger(cand.cited)
            principles.append(
                Principle(
                    principle_id=_principle_id(cand.text, cand.cited),
                    text=cand.text,
                    confidence=compute_confidence(ledger, now=now),
                    derived_from=[m.memory_id for m in cand.cited],
                )
            )
    return principles
