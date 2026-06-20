"""Structured memory-network data for the web UI.

Reuses the exact query patterns from ``recall.show`` but returns JSON-serializable
dicts instead of formatted terminal strings. These are *synchronous* functions that
drive the Hindsight client exactly as the working CLI does; the FastAPI handler runs
them in a worker thread (``asyncio.to_thread``) so each call gets a clean sync
context and never crosses the server's event loop — which is what triggers aiohttp's
"Timeout context manager should be used inside a task" error.
"""

from __future__ import annotations

from typing import Any

from recall.show import (
    _FACT_QUERY,
    _FACT_TOKENS,
    _FACT_TYPES,
    _MAX_PEOPLE,
    _REFLECT_BUDGET,
    _REFLECT_QUERY,
    _clean_reflection,
    _when,
)

ShowClient = Any


def episodic(client: ShowClient, bank_id: str) -> list[dict[str, str]]:
    """Return significant experiences with their time labels."""
    resp = client.recall(
        bank_id=bank_id,
        query="significant moments and events",
        types=["experience"],
    )
    results = getattr(resp, "results", None) or []
    return [{"text": r.text, "when": _when(r)} for r in results]


def semantic(client: ShowClient, bank_id: str) -> list[dict[str, str]]:
    """Return durable world facts learned from the conversations."""
    resp = client.recall(
        bank_id=bank_id,
        query="general facts and stable truths about people and the world",
        types=["world"],
    )
    results = getattr(resp, "results", None) or []
    return [{"text": r.text} for r in results]


def people(client: ShowClient, bank_id: str) -> list[dict[str, str]]:
    """Return entities with one short observation each."""
    resp = client.recall(
        bank_id=bank_id,
        query="the people in these conversations and what they are like",
        include_entities=True,
    )
    entities = getattr(resp, "entities", None) or {}
    out: list[dict[str, str]] = []
    for entity in list(entities.values())[:_MAX_PEOPLE]:
        name = getattr(entity, "canonical_name", None) or "(unknown)"
        observations = getattr(entity, "observations", None) or []
        note = getattr(observations[0], "text", "") if observations else ""
        out.append({"name": name, "note": note})
    return out


def principles(client: ShowClient, bank_id: str) -> list[dict[str, str]]:
    """Return evolving mental models (principles / beliefs)."""
    resp = client.list_mental_models(bank_id=bank_id)
    items = getattr(resp, "items", None) or []
    out: list[dict[str, str]] = []
    for item in items:
        name = getattr(item, "name", None) or "(unnamed)"
        content = getattr(item, "content", "") or ""
        out.append({"name": name, "content": content})
    return out


def _grounding_facts(client: ShowClient, bank_id: str) -> str:
    """Recall episodic + semantic facts to feed reflect as deterministic context."""
    facts: list[str] = []
    for fact_type in _FACT_TYPES:
        resp = client.recall(
            bank_id=bank_id,
            query=_FACT_QUERY,
            types=[fact_type],
            max_tokens=_FACT_TOKENS,
        )
        results = getattr(resp, "results", None) or []
        facts.extend(r.text for r in results)
    return "\n".join(f"- {fact}" for fact in facts)


def connections(client: ShowClient, bank_id: str) -> str:
    """Return the synthesized cross-conversation reflection — the money shot."""
    context = _grounding_facts(client, bank_id)
    resp = client.reflect(
        bank_id=bank_id,
        query=_REFLECT_QUERY,
        budget=_REFLECT_BUDGET,
        context=context,
    )
    return _clean_reflection((getattr(resp, "text", None) or "").strip())


def all_networks(client: ShowClient, bank_id: str) -> dict[str, Any]:
    """Bundle all five memory networks into one JSON-serializable payload."""
    return {
        "bank_id": bank_id,
        "episodic": episodic(client, bank_id),
        "semantic": semantic(client, bank_id),
        "people": people(client, bank_id),
        "principles": principles(client, bank_id),
        "connections": connections(client, bank_id),
    }
