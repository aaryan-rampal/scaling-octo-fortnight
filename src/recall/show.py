"""Render Hindsight's memory networks for a live demo.

Opens an embedded Hindsight client against a loaded bank and prints five
clearly-headed sections: episodic memory, semantic memory, people, evolving
principles, and a synthesized "connections" reflection. The rendering helpers
take a structurally-typed client (see :class:`ShowClient`) so tests can drive
them with a fake instead of booting the embedded server.
"""

from __future__ import annotations

import argparse
from typing import Any, Protocol

from recall.hindsight_runtime import embedded_hindsight

DEFAULT_BANK = "imessage-v0"

_WIDTH = 72
# We recall the grounding facts ourselves and feed them to reflect as context.
# Letting reflect decide whether to retrieve is non-deterministic on this bank:
# the same query sometimes synthesizes from 60+ memories and sometimes refuses
# with "I have no data". Supplying the facts up front makes the money shot
# reliable.
_FACT_QUERY = "significant moments, values, preferences, and facts about this person"
_FACT_TYPES = ("experience", "world")
_FACT_TOKENS = 3000
_REFLECT_QUERY = (
    "Based only on the facts provided in the context, describe what this person "
    "is like and what they value, then name one non-obvious connection between "
    "different parts of their life."
)
_REFLECT_BUDGET = "high"
# Cap the people list so the demo stays readable; the bank surfaces dozens of
# entities (cafes, songs, places) alongside the actual people.
_MAX_PEOPLE = 25
# The small reflect model narrates its tool use before the real answer. The
# synthesized answer begins at its first bold markdown header, so when that
# preamble is present we drop everything before it.
_ANSWER_MARKER = "**"


class ShowClient(Protocol):
    """Minimal client surface used by the rendering helpers.

    Structurally compatible with ``hindsight_client.Hindsight`` so the real
    client satisfies it, while letting tests substitute a fake without booting
    the embedded server.
    """

    def recall(self, *args: Any, **kwargs: Any) -> Any: ...

    def reflect(self, *args: Any, **kwargs: Any) -> Any: ...

    def list_mental_models(self, *args: Any, **kwargs: Any) -> Any: ...


def _header(title: str) -> str:
    """Return a banner line for one demo section."""
    return f"\n{'=' * _WIDTH}\n  {title}\n{'=' * _WIDTH}"


def _when(result: Any) -> str:
    """Best-effort human time label for a recall result, or empty string."""
    for field in ("occurred_start", "mentioned_at", "occurred_end"):
        value = getattr(result, field, None)
        if value:
            return str(value)
    return ""


def render_episodic(client: ShowClient, bank_id: str) -> str:
    """Render significant experiences with their time and involved people."""
    lines = [_header("1. EPISODIC MEMORY (experiences)")]
    resp = client.recall(
        bank_id=bank_id,
        query="significant moments and events",
        types=["experience"],
    )
    results = getattr(resp, "results", None) or []
    if not results:
        lines.append("  (no episodic memories surfaced)")
        return "\n".join(lines)
    for result in results:
        when = _when(result)
        involving = getattr(result, "entities", None) or []
        lines.append(f"\n  - {result.text}")
        if when:
            lines.append(f"      when: {when}")
        if involving:
            lines.append(f"      involving: {', '.join(involving)}")
    return "\n".join(lines)


def render_semantic(client: ShowClient, bank_id: str) -> str:
    """Render durable world facts learned from the conversations."""
    lines = [_header("2. SEMANTIC MEMORY (world facts)")]
    resp = client.recall(
        bank_id=bank_id,
        query="general facts and stable truths about people and the world",
        types=["world"],
    )
    results = getattr(resp, "results", None) or []
    if not results:
        lines.append("  (no semantic facts surfaced)")
        return "\n".join(lines)
    for result in results:
        lines.append(f"  - {result.text}")
    return "\n".join(lines)


def render_people(client: ShowClient, bank_id: str) -> str:
    """Render entities with one short observation each."""
    lines = [_header("3. PEOPLE (entities)")]
    resp = client.recall(
        bank_id=bank_id,
        query="the people in these conversations and what they are like",
        include_entities=True,
    )
    entities = getattr(resp, "entities", None) or {}
    if not entities:
        lines.append("  (no people surfaced)")
        return "\n".join(lines)
    for entity in list(entities.values())[:_MAX_PEOPLE]:
        name = getattr(entity, "canonical_name", None) or "(unknown)"
        observations = getattr(entity, "observations", None) or []
        note = getattr(observations[0], "text", "") if observations else ""
        lines.append(f"  - {name}")
        if note:
            lines.append(f"      {note}")
    return "\n".join(lines)


def render_principles(client: ShowClient, bank_id: str) -> str:
    """Render evolving mental models (principles / beliefs)."""
    lines = [_header("4. PRINCIPLES / EVOLVING BELIEFS")]
    resp = client.list_mental_models(bank_id=bank_id)
    items = getattr(resp, "items", None) or []
    if not items:
        lines.append("  (none surfaced yet)")
        return "\n".join(lines)
    for item in items:
        name = getattr(item, "name", None) or "(unnamed)"
        content = getattr(item, "content", "") or ""
        lines.append(f"  - {name}")
        if content:
            lines.append(f"      {content}")
    return "\n".join(lines)


def _clean_reflection(text: str) -> str:
    """Drop the model's pre-answer tool-use narration when present.

    The synthesized answer starts at the first bold markdown header. If such a
    header exists later in the text, anything before it is reasoning narration
    and is dropped; otherwise the text is returned unchanged.
    """
    marker = text.find(_ANSWER_MARKER)
    if marker > 0:
        return text[marker:].strip()
    return text


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
        facts.extend(result.text for result in results)
    return "\n".join(f"- {fact}" for fact in facts)


def render_connections(client: ShowClient, bank_id: str) -> str:
    """Render the synthesized cross-conversation reflection — the money shot."""
    lines = [_header("5. HINDSIGHT CONNECTIONS")]
    context = _grounding_facts(client, bank_id)
    resp = client.reflect(
        bank_id=bank_id,
        query=_REFLECT_QUERY,
        budget=_REFLECT_BUDGET,
        context=context,
    )
    text = _clean_reflection((getattr(resp, "text", None) or "").strip())
    if not text:
        lines.append("  (no connection synthesized)")
        return "\n".join(lines)
    lines.append(f"\n  {text}")
    return "\n".join(lines)


def render_all(client: ShowClient, bank_id: str) -> str:
    """Render every demo section for ``bank_id`` into a single string."""
    sections = (
        render_episodic,
        render_semantic,
        render_people,
        render_principles,
        render_connections,
    )
    return "\n".join(section(client, bank_id) for section in sections)


def show(bank_id: str) -> None:
    """Boot an embedded Hindsight client and print all demo sections.

    Args:
        bank_id: The memory bank to surface (must already be loaded).
    """
    print(f"Recall — memory networks for bank '{bank_id}'")
    with embedded_hindsight() as client:
        print(render_all(client, bank_id))


def main() -> None:
    """CLI entrypoint: ``python -m recall.show [--bank imessage-v0]``."""
    parser = argparse.ArgumentParser(description="Show Hindsight memory networks.")
    parser.add_argument("--bank", default=DEFAULT_BANK, help="Memory bank id.")
    args = parser.parse_args()
    show(args.bank)


if __name__ == "__main__":
    main()
