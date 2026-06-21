"""Live seams for rung ③ minting: embedding reader, recall→cards, proposer.

Wires three injectable pieces onto ``pipeline.mint``:

- :class:`PgVectorReader` — reads stored qwen embeddings from pg0's
  ``memory_units`` table so memories are never re-embedded.
- :func:`recall_to_cards` — calls Hindsight ``recall``, joins embeddings, and
  returns :class:`~pipeline.mint.MemoryCard` objects ready for clustering.
- :class:`QwenEmbedder` — embeds a *new* string (a proposed principle) via
  OpenRouter's qwen3-embedding-8b, matching Hindsight's vector space.
- :class:`LLMProposer` — the one stochastic seam: sends one cluster's texts to
  gemini via OpenRouter and parses back ``(principle_text, [memory_id, ...])``
  pairs. JSON parsing is defensive; malformed output yields an empty list.

None of the classes here touch principle logic — that stays in ``mint.py``.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

import psycopg2
from loguru import logger
from openai import OpenAI

from observability.compression import compress_message
from observability.sentry import capture_exception, gen_ai_span, record_gen_ai_usage
from pipeline.mint import MemoryCard


class VectorReader(Protocol):
    """Structural protocol for reading stored embeddings from a vector store.

    Both :class:`PgVectorReader` (live) and test fakes satisfy this; it keeps
    :func:`recall_to_cards` decoupled from the concrete pg0 class so it stays
    unit-testable without a running database.
    """

    def read(self, memory_ids: list[str]) -> dict[str, list[float]]:
        """Return id → embedding for each id that has a stored vector."""
        ...

    def close(self) -> None:
        """Release any resources held by the reader."""
        ...


_PG_DSN = "postgresql://hindsight:hindsight@127.0.0.1:5432/hindsight"

_EMBED_MODEL = "qwen/qwen3-embedding-8b"
_EMBED_DIM = 2000

_LLM_MODEL = "google/gemini-3.5-flash"

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Sent to gemini to elicit a JSON array of principle objects per cluster.
_SYSTEM_PROMPT = (
    "You extract enduring personal principles — the values, dispositions, and "
    "recurring patterns that define who this person is — from a cluster of their "
    "memories.\n"
    "\n"
    "A principle is fundamental to a person's character: how they think, what they "
    "value, how they relate to others, what drives them. It must hold across "
    "situations, not describe a single occasion.\n"
    "\n"
    "Do NOT produce a principle from:\n"
    "- one-off tasks or activities (e.g. analyzing a dataset, fixing a bug, a "
    "single purchase) — these are events, not character;\n"
    "- tool use, coding-session details, or technical minutiae;\n"
    "- anything an ASSISTANT/AI did or said in a chat — those describe the "
    "assistant, not this person. Only the person's own values count.\n"
    "When a cluster is just a narrow task or assistant activity with no enduring "
    "value behind it, return [].\n"
    "\n"
    "Rules:\n"
    '- Each principle must be ≤15 words, in the second person (e.g. "You value …").\n'
    "- State the underlying value or pattern, not the surface activity that "
    'revealed it (write "You protect time for deep focus", not "You analyzed '
    'JSON savings").\n'
    "- Every principle MUST cite 2 or more memory_ids FROM THE PROVIDED LIST.\n"
    "- Return ONLY a valid JSON array, no markdown fences, no prose.\n"
    '- Format: [{"text": "principle text", "memory_ids": ["id1", "id2"]}, ...]\n'
    "- If no enduring principle spans >=2 memories, return [].\n"
)

_USER_TEMPLATE = """Memories (id → text):
{entries}

Return the JSON array of principles now."""


def _parse_raw_vector(raw: Any) -> list[float]:
    """Parse a pgvector value that comes back as a string ``'[0.1,0.2,...]'``."""
    return [float(x) for x in str(raw).strip("[]").split(",")]


class PgVectorReader:
    """Reads stored qwen embeddings from pg0 for a list of memory ids.

    Opens one connection per reader instance (closed by :meth:`close` or the
    context-manager exit). The connection is held open so a batch of ids shares
    it rather than reconnecting per id.

    Args:
        dsn: libpq connection string; defaults to the embedded pg0 address.
    """

    def __init__(self, dsn: str = _PG_DSN) -> None:
        self._conn = psycopg2.connect(dsn)

    def read(self, memory_ids: list[str]) -> dict[str, list[float]]:
        """Return a mapping of memory_id → embedding for the given ids.

        Ids with no stored embedding are silently omitted; callers should treat
        missing embeddings as ``None`` (same as :class:`~pipeline.mint.MemoryCard`
        does).

        Args:
            memory_ids: UUIDs to look up.

        Returns:
            Dict of id → 2000-dim float list.
        """
        if not memory_ids:
            return {}
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id::text, embedding FROM memory_units WHERE id = ANY(%s::uuid[])",
            (memory_ids,),
        )
        result: dict[str, list[float]] = {}
        for row_id, raw_emb in cur.fetchall():
            if raw_emb is not None:
                result[row_id] = _parse_raw_vector(raw_emb)
        cur.close()
        return result

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __enter__(self) -> PgVectorReader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _source_from_tags(tags: list[str]) -> str:
    """Derive the originating source from a memory's tag list.

    Tags follow Hindsight's convention: the source name appears as a bare tag
    (e.g. ``"imessage"``, ``"spotify"``, ``"photos"``, ``"claude"``). Return the
    first matching tag, or ``"unknown"`` when none is found.

    Args:
        tags: The memory's tag list from Hindsight recall.

    Returns:
        One of ``imessage``, ``spotify``, ``photos``, ``claude``, or ``unknown``.
    """
    known = {"imessage", "spotify", "photos", "claude"}
    for tag in tags:
        if tag in known:
            return tag
    return "unknown"


def _ts_from_occurred(occurred_start: Any) -> str:
    """Return an ISO-8601 string from a recall result's ``occurred_start``.

    Hindsight may return a ``datetime`` object or an ISO string. Always produce
    a string so :class:`~pipeline.mint.MemoryCard` stays a pure-data type.

    Args:
        occurred_start: The raw ``occurred_start`` value from the recall result.

    Returns:
        ISO-8601 string; empty string when the value is absent or unparseable.
    """
    if occurred_start is None:
        return ""
    if hasattr(occurred_start, "isoformat"):
        return occurred_start.isoformat()
    return str(occurred_start)


def recall_to_cards(
    client: Any,
    query: str,
    bank_id: str,
    *,
    pg_reader: VectorReader | None = None,
    max_tokens: int = 6000,
) -> list[MemoryCard]:
    """Recall memories and join their stored embeddings into MemoryCards.

    Calls ``client.recall`` with ``types=["experience","world"]``, then looks up
    each result's embedding from pg0 via *pg_reader*. Deduplicates by id so a
    memory appearing under multiple types is included only once.

    Args:
        client: A live Hindsight client (from ``embedded_hindsight``).
        query: The recall query text.
        bank_id: The Hindsight bank to query.
        pg_reader: An open :class:`VectorReader`; if ``None``, a
            :class:`PgVectorReader` is created and closed after this call.
        max_tokens: Token budget forwarded to the recall call.

    Returns:
        Deduplicated list of :class:`~pipeline.mint.MemoryCard` objects with
        embeddings joined in (``None`` when pg0 has no stored vector for an id).
    """
    results = client.recall(
        bank_id=bank_id,
        query=query,
        types=["experience", "world"],
        max_tokens=max_tokens,
    )
    seen: dict[str, Any] = {}
    for r in results:
        if r.id not in seen:
            seen[r.id] = r

    ids = list(seen.keys())
    own_reader = pg_reader is None
    reader = pg_reader if pg_reader is not None else PgVectorReader()
    try:
        embeddings = reader.read(ids)
    finally:
        if own_reader:
            reader.close()

    cards: list[MemoryCard] = []
    for mid, r in seen.items():
        cards.append(
            MemoryCard(
                memory_id=mid,
                text=r.text,
                source=_source_from_tags(r.tags or []),
                ts=_ts_from_occurred(r.occurred_start),
                embedding=embeddings.get(mid),
            )
        )
    return cards


class QwenEmbedder:
    """Embeds a new string via OpenRouter's qwen3-embedding-8b (2000-dim).

    This is the ONE unavoidable embedding call: new principle text has no stored
    vector, so the novelty check requires embedding it fresh. Memories are never
    re-embedded — their vectors come from pg0 via :class:`PgVectorReader`.

    Args:
        api_key: OpenRouter API key; defaults to ``OPENROUTER_API_KEY`` env var.
    """

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set in the environment")
        self._client = OpenAI(api_key=key, base_url=_OPENROUTER_BASE)

    def embed(self, text: str) -> list[float]:
        """Return a 2000-dim qwen embedding for *text*.

        Args:
            text: The string to embed (typically a proposed principle).

        Returns:
            A 2000-element float list.
        """
        resp = self._client.embeddings.create(
            model=_EMBED_MODEL,
            input=[text],
            dimensions=_EMBED_DIM,
        )
        return resp.data[0].embedding


def _build_entries(cards: list[MemoryCard]) -> str:
    """Format cluster memory cards as ``id: text`` lines for the LLM prompt."""
    return "\n".join(f"{c.memory_id}: {c.text}" for c in cards)


def _parse_proposals(raw: str) -> list[tuple[str, list[str]]]:
    """Parse gemini's JSON output into ``(text, [memory_id, ...])`` pairs.

    Gemini sometimes wraps the array in markdown fences or adds trailing prose.
    This parser strips fences, extracts the first JSON array it finds, and
    silently drops any entry missing ``text`` or ``memory_ids``. Returns ``[]``
    on complete parse failure so the engine logs a skip rather than crashing.

    Args:
        raw: The raw LLM completion string.

    Returns:
        List of ``(principle_text, cited_ids)`` pairs; may be empty.
    """
    # Strip markdown fences if present.
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    # Find the outermost JSON array.
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        logger.warning("proposer: no JSON array found in LLM output; skipping cluster")
        return []
    try:
        items = json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.warning("proposer: JSON parse failed ({}); skipping cluster", exc)
        return []
    proposals: list[tuple[str, list[str]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        ids = item.get("memory_ids")
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(ids, list):
            continue
        str_ids = [str(i) for i in ids if i]
        if str_ids:
            proposals.append((text.strip(), str_ids))
    return proposals


class LLMProposer:
    """Proposes principles for a cluster via gemini on OpenRouter.

    Implements the :class:`~pipeline.mint.PrincipleProposer` Protocol. Shows the
    LLM only the current cluster's memories (cluster-first isolation), so every
    legal citation is a member of a small, known set — citations are verified
    downstream by :func:`~pipeline.mint.mint_cluster`, not here.

    Args:
        api_key: OpenRouter API key; defaults to ``OPENROUTER_API_KEY`` env var.
        model: OpenRouter chat model id.
    """

    def __init__(self, api_key: str | None = None, model: str = _LLM_MODEL) -> None:
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set in the environment")
        self._client = OpenAI(api_key=key, base_url=_OPENROUTER_BASE)
        self._model = model

    def propose(self, cards: list[MemoryCard]) -> list[tuple[str, list[str]]]:
        """Return ``(principle_text, cited_memory_ids)`` candidates for a cluster.

        Sends the cluster's memories as a user message and parses the JSON
        response. Returns an empty list when the LLM produces no valid output
        rather than raising — the engine handles empty proposals as a skip.

        Args:
            cards: The cluster's memories (shown to the LLM verbatim).

        Returns:
            Parsed ``(text, [id, ...])`` pairs; may be empty.
        """
        entries = _build_entries(cards)
        user_msg = _USER_TEMPLATE.format(entries=entries)
        # Metadata only — never the cluster's raw memory text (personal data).
        request_data = {"cluster_size": len(cards), "temperature": 0.3}
        with gen_ai_span(operation="chat", model=self._model, request_data=request_data) as span:
            # Optional Token Company pre-pass (records savings on this span when on).
            user_msg = compress_message(user_msg)
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.3,
                )
            except Exception as exc:
                logger.error("proposer: LLM call failed: {}: {}", type(exc).__name__, exc)
                capture_exception(exc, context={"stage": "propose", "model": self._model})
                return []
            record_gen_ai_usage(span, getattr(resp, "usage", None))
            raw = (resp.choices[0].message.content or "").strip()
            proposals = _parse_proposals(raw)
            span.set_data("gen_ai.response.proposal_count", len(proposals))
            return proposals
