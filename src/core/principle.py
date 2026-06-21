"""Rung ③/④ domain types — the principle graph (nodes + typed edges).

A principle is a one-line mental model the user reads ("keep weekends free,
unless close friends"). Principles are **graph nodes**, not a flat list: each
node cites the memories that back it (its evidence ledger), and typed **edges**
(rung ④) connect related principles. Both node and edge carry a non-empty
``derived_from`` of ``memory_id`` values — the provenance chain that lets any
principle trace memory -> unit -> raw Event.

Shapes are pinned by ``docs/v0-pipeline-contract.md`` (rung ③/④ output) and the
minting strategy in ``docs/rung3-minting-strategy.md``. The one invariant that
rots silently if broken (CLAUDE.md §2): a principle is born only by consolidation
reading real memories — never written directly — so an empty ledger is a snapped
chain and is rejected at construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: The typed relations a rung-④ edge may assert between two principles.
Relation = Literal["supports", "refines", "generalizes", "contradicts"]

#: The stance a single memory takes toward a principle in its evidence ledger.
Stance = Literal["supports", "weakens", "contradicts"]


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One memory's signed contribution to a principle's evidence ledger.

    Attributes:
        memory_id: The Hindsight memory backing this row; bottoms out at raw_data
            through the memory's own ``derived_from`` chain.
        stance: Whether this memory ``supports`` / ``weakens`` / ``contradicts``
            the principle — drives the ledger-derived confidence, never the LLM.
        source: Originating source of the memory (``imessage`` / ``spotify`` /
            ``photos``); feeds the source-diversity term in confidence.
        quote: The supporting span from the memory text (for display / audit).
        ts: ISO-8601 timestamp of the memory, used for recency weighting.
    """

    memory_id: str
    stance: Stance
    source: str
    quote: str
    ts: str


@dataclass(frozen=True, slots=True)
class Principle:
    """A rung-③ principle node: a one-line mental model with an evidence ledger.

    Attributes:
        principle_id: Stable id so rung-④ edges can reference this node.
        text: The one-line mental model surfaced to the user.
        confidence: ``0..1``, derived from the ledger structure (count, source
            diversity, recency, contradictions) — **not** the LLM's self-report.
        derived_from: The supporting ``memory_id``s (the ledger). Must hold at
            least two distinct ids — a principle is genuine synthesis across
            memories, not a restatement of one, and an empty/thin ledger is a
            snapped provenance chain.
    """

    principle_id: str
    text: str
    confidence: float
    derived_from: list[str]

    def __post_init__(self) -> None:
        """Enforce the ≥2-distinct-supports gate (rung ③) and the 0..1 range."""
        if len(set(self.derived_from)) < 2:
            raise ValueError(
                "Principle.derived_from must cite >=2 distinct supporting memory_ids; "
                f"got {self.derived_from!r} (a principle is synthesis, not a restatement)."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Principle.confidence must be in [0, 1]; got {self.confidence!r}")


@dataclass(frozen=True, slots=True)
class Edge:
    """A rung-④ typed, grounded edge between two principle nodes.

    The edge's evidence is drawn from a soft-scope neighborhood of the memory
    layer, so it may cite a memory that neither endpoint's ledger contains (e.g. a
    photo co-occurring in time with both). The cited ids are still bounded: a
    non-LLM check rejects any ``memory_id`` outside that neighborhood, so a passing
    edge is **grounded** (cites real in-scope memories), not entailment-verified.

    Attributes:
        src: The source ``Principle.principle_id``.
        dst: The destination ``Principle.principle_id``.
        relation: The typed relation ``src`` bears to ``dst``.
        derived_from: The ``memory_id``s justifying the relation (the edge
            ledger). Must hold at least one id — a bare, unevidenced edge is
            rejected.
    """

    src: str
    dst: str
    relation: Relation
    derived_from: list[str]

    def __post_init__(self) -> None:
        """Enforce a non-empty edge ledger and a non-self edge."""
        if not self.derived_from:
            raise ValueError(
                "Edge.derived_from must cite >=1 memory_id justifying the relation; "
                f"an empty edge ledger is a snapped provenance chain ({self.src}->{self.dst})."
            )
        if self.src == self.dst:
            raise ValueError(
                f"Edge must connect two distinct principles; got self-edge {self.src!r}"
            )
