"""Adapt a raw OpenRouter ``usage`` JSON dict to the attribute shape Sentry wants.

The adapters reach OpenRouter via raw ``httpx`` (not the openai SDK), so a
response's token counts arrive as a plain dict (``{"prompt_tokens": ...}``).
:func:`observability.sentry.record_gen_ai_usage` reads ``.prompt_tokens`` /
``.completion_tokens`` / ``.total_tokens`` attributes, mirroring the openai SDK's
usage object. ``UsageDict`` bridges the two so the same span helper works for
both the SDK-based (mint/link) and httpx-based (adapter) call sites.
"""

from __future__ import annotations


class UsageDict:
    """Expose an OpenRouter ``usage`` dict via the attributes Sentry reads.

    Tolerates ``None`` (a response without a usage block) by reporting ``None``
    for every count, which :func:`record_gen_ai_usage` already handles.
    """

    __slots__ = ("completion_tokens", "prompt_tokens", "total_tokens")

    def __init__(self, usage: dict | None) -> None:
        """Build from a raw usage dict (or ``None``).

        Args:
            usage: The ``usage`` object from an OpenRouter chat-completions
                response, or ``None`` when the response carried no usage block.
        """
        usage = usage or {}
        self.prompt_tokens = usage.get("prompt_tokens")
        self.completion_tokens = usage.get("completion_tokens")
        self.total_tokens = usage.get("total_tokens")
