"""The "why" agent — turn a principle's provenance trace into a short explanation.

Wraps the deterministic trace (:mod:`storage.trace`) with the one stochastic
step: an LLM that reads the principle and all of its grounding evidence
(memories + the raw events under each) and writes a short paragraph on *why* the
principle was inferred. The LLM sits behind the :class:`WhyExplainer` protocol —
mirroring :class:`pipeline.link.LLMEdgeProposer` — so tests inject a fake and run
with no network and no API key.

Tone rules (CLAUDE.md §1): conversational and reflective, **not** recommendation;
grounded **only** in the supplied evidence (never invents events); honest when
evidence is thin; ends forward-looking.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol

from loguru import logger

from storage.trace import PrincipleTrace, to_dict, trace_principle


class WhyExplainer(Protocol):
    """The stochastic seam: explain why a principle exists from its trace."""

    def explain(self, trace: PrincipleTrace) -> str:
        """Return a short, grounded explanation of why *trace* was inferred."""
        ...


def render_evidence(trace: PrincipleTrace) -> str:
    """Render a trace as the human-readable evidence block shown to the LLM.

    Pure function (no network) so the prompt body is unit-testable on its own.

    Args:
        trace: The principle trace to render.

    Returns:
        A plain-text block: the principle, then each memory with its raw events.
    """
    lines = [
        f'Principle: "{trace.text}"',
        f"Confidence: {trace.confidence:.2f}",
        "",
    ]
    if not trace.memories:
        lines.append("(No backing memories found — the evidence is empty.)")
        return "\n".join(lines)

    lines.append(
        "Evidence — the memories this was consolidated from, "
        "and the raw moments behind each:"
    )
    for i, mem in enumerate(trace.memories, 1):
        when = f" [{mem.occurred_start}]" if mem.occurred_start else ""
        lines.append(f"\n{i}. Memory ({mem.source}){when}: {mem.text}")
        if not mem.events:
            lines.append("   - (no raw events linked to this memory)")
        for ev in mem.events:
            lines.append(f'   - {ev.t_utc} ({ev.author_role}): "{ev.content}"  [{ev.raw_ref}]')
    return "\n".join(lines)


_SYSTEM = (
    "You explain WHY a personal principle was inferred about someone, using ONLY "
    "the evidence provided.\n"
    "The evidence is the principle's provenance: the memories it was consolidated "
    "from, and under each memory the raw messages/items those memories were "
    "extracted from.\n"
    "\n"
    "Write 2-4 sentences, addressed to the user as 'you'. Requirements:\n"
    "- Ground every claim in the supplied evidence and refer to specific moments. "
    "Never invent events, dates, names, or details that are not shown below.\n"
    "- Be conversational and reflective — this is a mirror, not advice. Do not "
    "recommend, prescribe, or tell the user what to do.\n"
    "- If the evidence is thin, say the read is tentative rather than overstating "
    "it.\n"
    "- End on a forward-looking note; never suggest going back to how things were.\n"
    "Return plain text only — no markdown, no preamble."
)


def explain_principle(
    conn: sqlite3.Connection,
    principle_id: str,
    explainer: WhyExplainer,
) -> dict | None:
    """Trace a principle and attach an LLM explanation of why it exists.

    Args:
        conn: An open connection to the provenance DB.
        principle_id: The ``principles.id`` to explain.
        explainer: The injectable LLM seam (live or fake).

    Returns:
        The trace projected to a dict (see :func:`storage.trace.to_dict`) with an
        added ``"why"`` key, or ``None`` when no principle has that id.
    """
    trace = trace_principle(conn, principle_id)
    if trace is None:
        return None
    why = explainer.explain(trace)
    result = to_dict(trace)
    result["why"] = why
    return result


class LLMWhyExplainer:
    """Live :class:`WhyExplainer` — explains a principle via an OpenRouter model.

    Reuses the OpenRouter/openai client pattern from
    :class:`pipeline.link.LLMEdgeProposer`. The ``openai`` import is deferred to
    construction so importing this module never requires the dependency or a key.

    Args:
        api_key: OpenRouter API key; defaults to ``OPENROUTER_API_KEY`` env var
            (Doppler injects it at runtime).
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

    def explain(self, trace: PrincipleTrace) -> str:
        """Ask the model for a grounded explanation; returns its text (or empty).

        Args:
            trace: The principle trace to explain.

        Returns:
            The model's plain-text explanation, or ``""`` if the call fails.
        """
        user_msg = render_evidence(trace)
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.4,
            )
        except Exception as exc:
            logger.error("why explainer: LLM call failed: {}: {}", type(exc).__name__, exc)
            return ""
        return (resp.choices[0].message.content or "").strip()
