"""Optional Token Company prompt compression, gated and Sentry-instrumented.

The Token Company (https://thetokencompany.com) deterministically deletes
low-information tokens from a prompt before it reaches the model, cutting input
tokens at roughly flat accuracy. This module is a thin, opt-in pre-pass over a
single message string so the A/B is a one-line wrap at the call site.

Two switches control it, so the default pipeline is byte-for-byte unchanged:

- ``RETURN_TTC_COMPRESS=1`` turns the pass on (off / unset = passthrough).
- ``TTC_API_KEY`` (a ``ttc-`` key) must be present, else passthrough.

When active, savings are recorded on the *currently active* Sentry span as
``gen_ai.request.compressed`` plus ``gen_ai.usage.tokens_saved`` /
``...compression_ratio``, so the existing AI Agents dashboard shows the A/B
side by side (filter spans by ``compressed:true`` vs ``compressed:false``).

Privacy note: prompts here are minted-principle context derived from personal
memories, so the *text* is sent to a third party only when compression is
explicitly enabled — never by default. Keep this off for runs on real user data
unless that egress is acceptable for the demo.
"""

from __future__ import annotations

import os

import sentry_sdk
from loguru import logger

#: Default compression model (vendor-recommended); ~10-40% input-token cut.
_TTC_MODEL = "bear-2"

#: Aggressiveness for content the model must answer from (vendor guidance:
#: 0.05-0.2 for answer-bearing content, higher for background). Principle
#: minting reads the cluster's memories to produce the answer, so stay low.
_TTC_AGGRESSIVENESS = 0.2


def compression_enabled() -> bool:
    """Return whether the compression pre-pass should run this process.

    True only when ``RETURN_TTC_COMPRESS`` is truthy *and* a ``TTC_API_KEY`` is
    present. Keeping both checks here means call sites never branch on config.
    """
    if os.environ.get("RETURN_TTC_COMPRESS", "").strip().lower() not in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("TTC_API_KEY"))


def compress_message(text: str) -> str:
    """Compress one prompt string via The Token Company, or pass it through.

    Returns ``text`` unchanged (and records nothing) when compression is
    disabled or the API call fails — compression is an optimization, never a
    correctness dependency, so a vendor outage must not break minting. When it
    succeeds, savings are attached to the active Sentry span.

    Args:
        text: The user-message content to compress (personal-derived; only sent
            to the vendor when compression is explicitly enabled).

    Returns:
        The compressed string on success, otherwise the original ``text``.
    """
    if not compression_enabled():
        _mark_span(compressed=False)
        return text
    try:
        from thetokencompany import TheTokenCompany

        client = TheTokenCompany(api_key=os.environ["TTC_API_KEY"])
        result = client.compress(
            text, model=_TTC_MODEL, aggressiveness=_TTC_AGGRESSIVENESS
        )
    except Exception as exc:  # vendor/network/import failure → passthrough
        logger.warning("token-company compression skipped: {}: {}", type(exc).__name__, exc)
        _mark_span(compressed=False)
        return text

    _mark_span(
        compressed=True,
        input_tokens=getattr(result, "input_tokens", None),
        output_tokens=getattr(result, "output_tokens", None),
    )
    return getattr(result, "output", text)


def _mark_span(
    *,
    compressed: bool,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Annotate the active Sentry span with compression A/B attributes.

    Derives ``tokens_saved`` and ``compression_ratio`` from the vendor's
    pre/post counts (the 0.3.2 ``CompressResponse`` exposes only ``input_tokens``
    / ``output_tokens``). No-op when no span is active (Sentry disabled or
    outside a ``gen_ai_span``), so it is safe to call unconditionally from
    :func:`compress_message`.
    """
    span = sentry_sdk.get_current_span()
    if span is None:
        return
    span.set_data("gen_ai.request.compressed", compressed)
    if input_tokens is not None and output_tokens is not None:
        span.set_data("gen_ai.usage.precompression_input_tokens", input_tokens)
        span.set_data("gen_ai.usage.postcompression_input_tokens", output_tokens)
        span.set_data("gen_ai.usage.compression_tokens_saved", input_tokens - output_tokens)
        if output_tokens > 0:
            span.set_data("gen_ai.usage.compression_ratio", input_tokens / output_tokens)
