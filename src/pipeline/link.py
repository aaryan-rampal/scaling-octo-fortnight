"""Rung ④ — MERGE near-duplicate principles then LINK related ones with typed edges.

Two passes over the principle set produced by rung ③:

**MERGE pass** — collapses near-duplicate principles (cosine ≥ 0.80) using
single-link grouping, preserving the UNION of all member ``derived_from`` ids
(no memory_id is ever dropped). The survivor text is the highest-confidence
member's text. Confidence is recomputed from the union ledger via
:func:`~pipeline.mint.compute_confidence`.

**LINKING pass** -- for each pair of (merged) principles in the 0.60-0.80 cosine
band (related-but-not-duplicate), an LLM is asked for a typed :class:`~core.principle.Edge`.
The allowed citation neighborhood for an edge is the union of both principles'
``derived_from`` memory_ids (the v0 simplification; full soft-scope recall-similar
neighborhood is the richer spec). Any cited memory_id outside that neighborhood
is dropped before the edge is stored; edges with 0 surviving citations are
rejected.

Injected seams — both the embedder and LLM are protocol-typed so tests run
without a network:

- :class:`PrincipleEmbedder` — embeds a principle text string → vector.
- :class:`EdgeProposer` — sees two principles and their shared neighborhood ids;
  returns a ``(relation, [cited_ids])`` proposal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Protocol

from loguru import logger

from core.principle import Edge, LedgerRow, Principle, Relation
from observability.sentry import capture_exception, gen_ai_span, record_gen_ai_usage
from pipeline.mint import MemoryCard, compute_confidence

#: Pairs at or above this cosine are merge candidates (near-duplicates).
MERGE_COSINE = 0.80

#: Lower bound of the "related" band that triggers a linking proposal.
LINK_COSINE_LO = 0.60

#: Upper bound of the "related" band (== MERGE_COSINE, pairs above go to merge).
LINK_COSINE_HI = MERGE_COSINE


# ---------------------------------------------------------------------------
# Protocols (inject-able seams)
# ---------------------------------------------------------------------------


class PrincipleEmbedder(Protocol):
    """Embeds a principle text string into a vector (same space as memories)."""

    def embed(self, text: str) -> list[float]:
        """Return a float vector for *text*."""
        ...


class EdgeProposer(Protocol):
    """The stochastic seam: propose a typed edge between two principles.

    Shown both principle texts and the memory_ids in the allowed neighborhood.
    Returns ``(relation, [cited_memory_ids])`` or ``None`` when no edge is warranted.
    """

    def propose_edge(
        self,
        src: Principle,
        dst: Principle,
        neighborhood: list[str],
    ) -> tuple[Relation, list[str]] | None:
        """Return an edge proposal, or ``None`` to skip this pair.

        Args:
            src: Source principle.
            dst: Destination principle.
            neighborhood: The allowed citation set (union of both derived_from).

        Returns:
            ``(relation, cited_ids)`` where cited_ids ⊆ neighborhood, or ``None``.
        """
        ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    """Return cosine similarity of two equal-length vectors (0 if degenerate)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _merged_principle_id(text: str, derived_from: list[str]) -> str:
    """Stable id from text and sorted union of derived_from ids."""
    payload = "\x1f".join([text, *sorted(derived_from)])
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# MERGE pass
# ---------------------------------------------------------------------------


def _embed_all(principles: list[Principle], embedder: PrincipleEmbedder) -> dict[str, list[float]]:
    """Embed every principle text, keyed by principle_id.

    Args:
        principles: The principles to embed.
        embedder: The embedding callable.

    Returns:
        Dict mapping principle_id → float vector.
    """
    result: dict[str, list[float]] = {}
    for p in principles:
        result[p.principle_id] = embedder.embed(p.text)
        logger.debug("embedded principle {:.8}…: {!r}", p.principle_id, p.text[:60])
    return result


def _build_merge_groups(
    principles: list[Principle],
    embeddings: dict[str, list[float]],
    *,
    threshold: float = MERGE_COSINE,
) -> list[list[Principle]]:
    """Group near-duplicate principles by single-link cosine clustering.

    Args:
        principles: All principles to group.
        embeddings: Precomputed vectors, keyed by principle_id.
        threshold: Cosine threshold; pairs at or above join the same group.

    Returns:
        Groups of >=1 principle each (singletons = unchanged).
    """
    groups: list[list[Principle]] = []
    for principle in principles:
        emb = embeddings.get(principle.principle_id)
        if emb is None:
            groups.append([principle])
            continue
        placed = False
        for group in groups:
            for member in group:
                m_emb = embeddings.get(member.principle_id)
                if m_emb is not None and _cosine(emb, m_emb) >= threshold:
                    group.append(principle)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            groups.append([principle])
    return groups


def _merge_group(group: list[Principle], cards_by_id: dict[str, MemoryCard]) -> Principle:
    """Collapse a merge-group into one principle.

    The survivor text is the highest-confidence member's text. The merged
    ``derived_from`` is the deduplicated UNION of all member ids (no id is
    ever dropped). Confidence is recomputed from the rebuilt union ledger.

    Args:
        group: Principles to collapse (>=1).
        cards_by_id: MemoryCards keyed by memory_id, used to rebuild ledger rows.

    Returns:
        A single merged :class:`~core.principle.Principle`.
    """
    if len(group) == 1:
        return group[0]

    survivor = max(group, key=lambda p: p.confidence)
    logger.info(
        "merge-group: {} principles → survivor text {!r}",
        len(group),
        survivor.text[:80],
    )
    for p in group:
        if p.principle_id != survivor.principle_id:
            logger.info("  collapsing {!r}", p.text[:80])

    union_ids: list[str] = list(dict.fromkeys(mid for p in group for mid in p.derived_from))
    ledger = _rebuild_ledger(union_ids, cards_by_id)
    confidence = compute_confidence(ledger)
    new_id = _merged_principle_id(survivor.text, union_ids)
    return Principle(
        principle_id=new_id,
        text=survivor.text,
        confidence=confidence,
        derived_from=union_ids,
    )


def _rebuild_ledger(memory_ids: list[str], cards_by_id: dict[str, MemoryCard]) -> list[LedgerRow]:
    """Rebuild a supports-only ledger for a list of memory_ids.

    Unknown ids (no card) are silently skipped — they may have been in the
    union from a different cluster's run where the card wasn't recalled.

    Args:
        memory_ids: The ordered list of ids to include.
        cards_by_id: The available MemoryCards.

    Returns:
        LedgerRows for every id that has a card.
    """
    rows: list[LedgerRow] = []
    for mid in memory_ids:
        card = cards_by_id.get(mid)
        if card is None:
            logger.debug("rebuild_ledger: no card for {}; skipping", mid)
            continue
        rows.append(
            LedgerRow(
                memory_id=mid,
                stance="supports",
                source=card.source,
                quote=card.text,
                ts=card.ts,
            )
        )
    return rows


def run_merge(
    principles: list[Principle],
    embedder: PrincipleEmbedder,
    cards_by_id: dict[str, MemoryCard],
    *,
    threshold: float = MERGE_COSINE,
) -> list[Principle]:
    """MERGE pass: embed all principles and collapse near-duplicate groups.

    Args:
        principles: The rung-③ principles to merge.
        embedder: Embeds principle texts.
        cards_by_id: MemoryCards keyed by id, for ledger reconstruction.
        threshold: Cosine similarity at/above which two principles are merged.

    Returns:
        Deduplicated principle list (N → M where M ≤ N).
    """
    if not principles:
        return []

    logger.info("merge: embedding {} principles", len(principles))
    embeddings = _embed_all(principles, embedder)

    groups = _build_merge_groups(principles, embeddings, threshold=threshold)
    multi = sum(1 for g in groups if len(g) > 1)
    logger.info(
        "merge: {} groups ({} collapsed) from {} principles",
        len(groups),
        multi,
        len(principles),
    )

    merged: list[Principle] = []
    for group in groups:
        merged.append(_merge_group(group, cards_by_id))
    logger.info("merge: {} → {} principles", len(principles), len(merged))
    return merged


# ---------------------------------------------------------------------------
# LINKING pass
# ---------------------------------------------------------------------------


def _pair_neighborhood(src: Principle, dst: Principle) -> list[str]:
    """Return the union of both principles' derived_from as the citation neighborhood.

    v0 simplification: the allowed set is the union of both ledgers' memory_ids.
    The richer soft-scope spec (recall-similar memories ± temporal window) is
    deferred — noted in link_principles.py's docstring.

    Args:
        src: Source principle.
        dst: Destination principle.

    Returns:
        Deduplicated list of memory_ids in insertion order.
    """
    return list(dict.fromkeys(list(src.derived_from) + list(dst.derived_from)))


def _verify_edge_citations(cited: list[str], neighborhood: list[str]) -> list[str]:
    """Keep only cited ids that are in the allowed neighborhood.

    Non-LLM guard: an id the model invented or hallucinated is simply dropped.
    The edge is subsequently rejected if 0 ids survive (Edge requires >=1).

    Args:
        cited: memory_ids the LLM returned.
        neighborhood: The allowed citation set.

    Returns:
        The subset of ``cited`` present in ``neighborhood``, in input order.
    """
    allowed = set(neighborhood)
    return [mid for mid in cited if mid in allowed]


def run_linking(
    principles: list[Principle],
    embedder: PrincipleEmbedder,
    proposer: EdgeProposer,
    *,
    lo: float = LINK_COSINE_LO,
    hi: float = LINK_COSINE_HI,
    limit: int = 0,
) -> list[Edge]:
    """LINKING pass: propose typed edges for principle pairs in the cosine band.

    Args:
        principles: The merged principles to link.
        embedder: Embeds principle texts for pair similarity.
        proposer: The LLM seam that proposes typed edges.
        lo: Lower bound of the "related" cosine band.
        hi: Upper bound; pairs at or above go to merge, not link.
        limit: Max pairs to send to the LLM (0 = all). For smoke runs.

    Returns:
        Accepted :class:`~core.principle.Edge` objects.
    """
    if not principles:
        return []

    logger.info("link: embedding {} principles for pair similarity", len(principles))
    embeddings = {p.principle_id: embedder.embed(p.text) for p in principles}

    pairs: list[tuple[Principle, Principle, float]] = []
    for i, src in enumerate(principles):
        for dst in principles[i + 1 :]:
            e_src = embeddings.get(src.principle_id)
            e_dst = embeddings.get(dst.principle_id)
            if e_src is None or e_dst is None:
                continue
            sim = _cosine(e_src, e_dst)
            if lo <= sim < hi:
                pairs.append((src, dst, sim))

    logger.info("link: {} pairs in cosine band [{}, {})", len(pairs), lo, hi)
    if limit:
        pairs = pairs[:limit]
        logger.info("link: limiting to first {} pairs (--limit)", limit)

    edges: list[Edge] = []
    for idx, (src, dst, sim) in enumerate(pairs, 1):
        neighborhood = _pair_neighborhood(src, dst)
        logger.info(
            "[{}/{}] pair sim={:.3f} | {!r} ↔ {!r}",
            idx,
            len(pairs),
            sim,
            src.text[:50],
            dst.text[:50],
        )
        proposal = proposer.propose_edge(src, dst, neighborhood)
        if proposal is None:
            logger.info("  -> skip (proposer returned None)")
            continue

        relation, cited_raw = proposal
        cited = _verify_edge_citations(cited_raw, neighborhood)
        if not cited:
            logger.info(
                "  -> rejected (0 citations survived verification; {} proposed)",
                len(cited_raw),
            )
            continue

        try:
            edge = Edge(
                src=src.principle_id,
                dst=dst.principle_id,
                relation=relation,
                derived_from=cited,
            )
        except ValueError as exc:
            logger.info("  -> rejected ({})", exc)
            continue

        edges.append(edge)
        logger.info(
            "  -> accepted {} (cited={}, total edges: {})",
            relation,
            len(cited),
            len(edges),
        )

    logger.info("link: {} edges from {} pairs", len(edges), len(pairs))
    return edges


# ---------------------------------------------------------------------------
# LLM edge proposer (live seam — reuses OpenRouter/gemini pattern)
# ---------------------------------------------------------------------------

_EDGE_SYSTEM = (
    "You identify typed relationships between two personal principles.\n"
    "\n"
    "Given Principle A, Principle B, and a list of memory_ids that ground both,\n"
    "return a JSON object with:\n"
    '  "relation": one of "supports" | "refines" | "generalizes" | "contradicts"\n'
    '  "memory_ids": list of >=1 memory_ids FROM THE PROVIDED LIST that justify the relation\n'
    "\n"
    "Definitions:\n"
    "  supports     — A and B reinforce the same underlying value\n"
    "  refines      — A is a more specific version of B (or B of A)\n"
    "  generalizes  — A is a broader abstraction of B (or B of A)\n"
    "  contradicts  — A and B pull in opposing directions\n"
    "\n"
    "Return ONLY valid JSON. No markdown. If no clear relation exists, return null.\n"
    'Example: {"relation": "refines", "memory_ids": ["id1", "id2"]}\n'
)

_EDGE_USER = """Principle A: {text_a}
Principle B: {text_b}

Memory IDs you may cite (pick >=1):
{ids}

Return the JSON object or null."""


class LLMEdgeProposer:
    """Proposes typed edges between principles via gemini on OpenRouter.

    Implements :class:`EdgeProposer`. Shows the LLM both principle texts and the
    allowed memory_ids. Citations are verified downstream by :func:`run_linking`.

    Args:
        api_key: OpenRouter API key; defaults to ``OPENROUTER_API_KEY`` env var.
        model: OpenRouter chat model id.
    """

    def __init__(self, api_key: str | None = None, model: str = "google/gemini-3.5-flash") -> None:
        import os

        from openai import OpenAI

        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set in the environment")
        self._client = OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")
        self._model = model

    def propose_edge(
        self,
        src: Principle,
        dst: Principle,
        neighborhood: list[str],
    ) -> tuple[Relation, list[str]] | None:
        """Ask the LLM for a typed relation + justifying memory_ids.

        Args:
            src: Source principle.
            dst: Destination principle.
            neighborhood: Allowed citation ids.

        Returns:
            ``(relation, cited_ids)`` or ``None`` when no edge is warranted or
            the LLM returns an unparseable response.
        """
        ids_str = "\n".join(f"  {mid}" for mid in neighborhood)
        user_msg = _EDGE_USER.format(text_a=src.text, text_b=dst.text, ids=ids_str)
        # Metadata only — neighborhood size, not the principle texts (personal data).
        request_data = {"neighborhood_size": len(neighborhood), "temperature": 0.2}
        with gen_ai_span(operation="chat", model=self._model, request_data=request_data) as span:
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": _EDGE_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.2,
                )
            except Exception as exc:
                logger.error("edge proposer: LLM call failed: {}: {}", type(exc).__name__, exc)
                capture_exception(exc, context={"stage": "link", "model": self._model})
                return None

            record_gen_ai_usage(span, getattr(resp, "usage", None))
            raw = (resp.choices[0].message.content or "").strip()
            return _parse_edge_proposal(raw)


def _parse_edge_proposal(raw: str) -> tuple[Relation, list[str]] | None:
    """Parse the LLM's JSON edge proposal.

    Accepts: a JSON object with "relation" and "memory_ids", or the literal
    ``null`` / empty / non-JSON (all treated as no-edge). Strips markdown fences.

    Args:
        raw: The raw LLM completion string.

    Returns:
        ``(relation, cited_ids)`` or ``None``.
    """
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        logger.warning("edge proposer: no JSON object in LLM output; skipping pair")
        return None
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.warning("edge proposer: JSON parse failed ({}); skipping pair", exc)
        return None

    relation = obj.get("relation")
    ids = obj.get("memory_ids")
    valid_relations: set[Any] = {"supports", "refines", "generalizes", "contradicts"}
    if relation not in valid_relations:
        logger.warning("edge proposer: invalid relation {!r}; skipping pair", relation)
        return None
    if not isinstance(ids, list):
        logger.warning("edge proposer: memory_ids missing or not a list; skipping pair")
        return None
    str_ids = [str(i) for i in ids if i]
    if not str_ids:
        return None
    return relation, str_ids  # type: ignore[return-value]
