"""Sentry initialization and a span helper for the LLM minting chain.

Sentry is the project's error + AI-agent observability layer. Two responsibilities
live here:

- :func:`init_sentry` — boot the SDK once per process from ``SENTRY_DSN``. When the
  DSN is unset (local dev, tests, CI without Doppler) it is a no-op, so keyless runs
  and the test suite are unaffected.
- :func:`gen_ai_span` — a context manager that emits an OpenTelemetry-style
  ``gen_ai.*`` span around a single LLM call. OpenRouter is reached via the raw
  ``openai`` SDK, which Sentry does NOT auto-instrument, so this is what makes the
  minting chain appear in Sentry's AI Agents dashboard.

Privacy: spans carry only metadata (model id, token counts, latency, outcome) — never
raw memory text or prompts. Raw data is iMessage-derived and stays out of third-party
telemetry, consistent with the repo's local-first stance.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

import sentry_sdk
from loguru import logger
from sentry_sdk.integrations.openai import OpenAIIntegration

#: Sample rate for performance traces. 1.0 (capture all) is correct for a demo /
#: single-user tool where volume is tiny and every trace is worth seeing.
_TRACES_SAMPLE_RATE = 1.0

#: Map loguru level names to the Sentry Logs API methods.
_SENTRY_LOG_METHODS = ("trace", "debug", "info", "warning", "error", "fatal")


def init_sentry(*, component: str) -> bool:
    """Initialize the Sentry SDK once for this process, if a DSN is configured.

    Reads ``SENTRY_DSN`` from the environment (injected by Doppler in this repo).
    When it is unset the function returns ``False`` without initializing, so tests
    and offline runs behave exactly as before. The FastAPI integration is enabled
    implicitly when ``fastapi`` is importable; no per-call wiring is needed.

    Args:
        component: A short label for the entry point (e.g. ``"api"``, ``"cli"``)
            recorded as a tag so traces from the web server and the pipeline are
            distinguishable in Sentry.

    Returns:
        ``True`` if Sentry was initialized, ``False`` if no DSN was present.
    """
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.debug("SENTRY_DSN unset; Sentry disabled for component {!r}", component)
        return False

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=_TRACES_SAMPLE_RATE,
        # Personal message data must never leave the device in telemetry. Keeping
        # PII off means prompts/completions are not attached to events or spans.
        send_default_pii=False,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "dev"),
        # Auto-instrument the openai client (used by propose/link/adapters via
        # OpenRouter) into AI spans with token usage and cost. include_prompts is
        # False so prompt/response text — personal data — never reaches Sentry.
        integrations=[OpenAIIntegration(include_prompts=False)],
        # Enable the Logs product so loguru records flow as first-class searchable
        # logs (not only breadcrumbs). Experimental flag in sentry-sdk 2.x.
        _experiments={"enable_logs": True},
    )
    sentry_sdk.set_tag("component", component)
    _add_breadcrumb_sink()
    _add_sentry_logs_sink()
    logger.info("Sentry initialized for component {!r}", component)
    return True


def _add_breadcrumb_sink() -> None:
    """Forward every loguru record to Sentry as a breadcrumb.

    The pipeline already emits rich progress via loguru (``log_progress`` heartbeats,
    per-cluster accept/reject lines, retain timing). Mirroring those records as
    breadcrumbs means any later error or transaction carries that trail for free —
    no per-call-site wiring. Only the message + level cross over; loguru records hold
    no raw memory text (progress lines carry counts and ids, not message bodies).
    """

    def _sink(message: Any) -> None:
        record = message.record
        sentry_sdk.add_breadcrumb(
            category=record["name"],
            message=record["message"],
            level=record["level"].name.lower(),
        )

    logger.add(_sink, level="INFO")


def _add_sentry_logs_sink() -> None:
    """Forward loguru records to the Sentry Logs product as structured logs.

    Unlike breadcrumbs (which only surface attached to an error or transaction),
    Sentry Logs are first-class, independently searchable entries in the Logs tab.
    Each record's already-formatted message is sent at the matching level, tagged
    with the originating module. Levels loguru emits but Sentry's logger lacks
    (e.g. ``success``) fall back to ``info``. No raw memory text is logged — the
    pipeline's loguru lines carry counts and ids, not message bodies.
    """
    from sentry_sdk import logger as sentry_logger

    def _sink(message: Any) -> None:
        record = message.record
        level = record["level"].name.lower()
        emit = getattr(sentry_logger, level, None)
        if emit is None or level not in _SENTRY_LOG_METHODS:
            emit = sentry_logger.info
        # Pass the pre-rendered text as a literal template (no further formatting)
        # plus the source module as a searchable attribute.
        emit("{message}", message=record["message"], module=record["name"])

    logger.add(_sink, level="INFO")


@contextlib.contextmanager
def gen_ai_span(*, operation: str, model: str, request_data: dict[str, Any]) -> Iterator[Any]:
    """Emit a ``gen_ai.*`` span around one LLM call for the AI Agents dashboard.

    Sets the OpenTelemetry GenAI semantic-convention attributes Sentry reads to
    render the AI Agents view. The yielded span is a no-op stand-in when Sentry is
    uninitialized, so call sites need no conditional. Token usage is recorded by the
    caller via :func:`record_gen_ai_usage` after the response returns.

    Args:
        operation: The GenAI operation name (e.g. ``"chat"``).
        model: The model id sent to the provider (e.g. ``"google/gemini-3.5-flash"``).
        request_data: Metadata-only attributes (cluster size, temperature, …). MUST
            NOT contain raw memory text or prompts.

    Yields:
        The active Sentry span, or a no-op span when Sentry is disabled.
    """
    with sentry_sdk.start_span(op=f"gen_ai.{operation}", name=f"{operation} {model}") as span:
        span.set_data("gen_ai.system", "openrouter")
        span.set_data("gen_ai.operation.name", operation)
        span.set_data("gen_ai.request.model", model)
        for key, value in request_data.items():
            span.set_data(f"gen_ai.request.{key}", value)
        yield span


def set_measurement(name: str, value: float, unit: str = "none") -> None:
    """Attach a numeric measurement to the active transaction.

    Measurements (token spend, clusters processed, principles minted, accept-rate,
    elapsed) become queryable metrics on the trace in Sentry. No-op when Sentry is
    disabled or there is no active transaction.

    Args:
        name: Measurement key (e.g. ``"principles_minted"``).
        value: Numeric value.
        unit: Sentry measurement unit (e.g. ``"none"``, ``"second"``, ``"ratio"``).
    """
    sentry_sdk.set_measurement(name, value, unit)


def capture_exception(exc: BaseException, *, context: dict[str, Any] | None = None) -> None:
    """Report a caught exception to Sentry as an Issue, with optional tags.

    The pipeline catches and logs many failures (a cluster's LLM call, an adapter
    enrichment) and continues rather than crashing. Those are invisible to error
    monitoring unless reported explicitly. This is a no-op when Sentry is disabled.

    Args:
        exc: The caught exception.
        context: Optional non-PII tags (e.g. ``{"stage": "mint", "cluster": 3}``)
            attached to the Sentry event scope. MUST NOT contain raw memory text.
    """
    with sentry_sdk.new_scope() as scope:
        for key, value in (context or {}).items():
            scope.set_tag(key, value)
        sentry_sdk.capture_exception(exc)


def record_gen_ai_usage(span: Any, usage: Any) -> None:
    """Attach token-usage counts from an OpenAI-compatible response to a span.

    Args:
        span: The span returned by :func:`gen_ai_span`.
        usage: The ``response.usage`` object (``prompt_tokens`` / ``completion_tokens``
            / ``total_tokens``); ``None`` is tolerated and skipped.
    """
    if usage is None:
        return
    span.set_data("gen_ai.usage.input_tokens", getattr(usage, "prompt_tokens", None))
    span.set_data("gen_ai.usage.output_tokens", getattr(usage, "completion_tokens", None))
    span.set_data("gen_ai.usage.total_tokens", getattr(usage, "total_tokens", None))
