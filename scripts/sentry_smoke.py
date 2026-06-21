"""Live Sentry smoke test: fire one of each primitive, then verify in Sentry.

Runs under Doppler (real ``SENTRY_DSN``) and exercises every observability path
once, inside a transaction, with a unique run tag so the events are easy to find:

- ``init_sentry`` boot (+ loguru -> Sentry Logs sink)
- loguru lines at each level -> Sentry **Logs** product
- a ``gen_ai`` span with token usage -> AI Agents dashboard
- ``set_measurement`` metrics on the transaction
- ``capture_exception`` -> an Issue

It makes NO OpenRouter calls and needs no bank — pure telemetry. After it runs,
query Sentry (MCP / dashboard) for ``smoke_run`` to confirm each shows up.

Run::

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/sentry_smoke.py
"""

from __future__ import annotations

import time
import uuid

import sentry_sdk
from loguru import logger

from observability.sentry import (
    capture_exception,
    gen_ai_span,
    init_sentry,
    record_gen_ai_usage,
    set_measurement,
)
from observability.usage import UsageDict


def main() -> None:
    """Emit one of every Sentry primitive under a unique run tag."""
    run_id = uuid.uuid4().hex[:8]
    enabled = init_sentry(component="smoke")
    if not enabled:
        logger.error("SENTRY_DSN unset — run under Doppler so the DSN is injected.")
        return

    sentry_sdk.set_tag("smoke_run", run_id)
    logger.info("sentry smoke: starting run {}", run_id)

    with sentry_sdk.start_transaction(op="smoke", name=f"sentry_smoke {run_id}"):
        # 1. Logs at each level -> Sentry Logs product (via the loguru sink).
        logger.debug("smoke[{}]: debug line", run_id)
        logger.info("smoke[{}]: info line", run_id)
        logger.warning("smoke[{}]: warning line", run_id)
        logger.error("smoke[{}]: error line", run_id)

        # 2. A gen_ai span with synthetic token usage -> AI Agents dashboard.
        with gen_ai_span(
            operation="chat",
            model="google/gemini-3.5-flash",
            request_data={"task": "smoke", "smoke_run": run_id},
        ) as span:
            time.sleep(0.05)
            usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
            record_gen_ai_usage(span, UsageDict(usage))

        # 3. Measurements -> queryable metrics on the transaction.
        set_measurement("smoke_units", 42, "none")
        set_measurement("smoke_ratio", 0.75, "ratio")

        # 4. A captured exception -> a Sentry Issue (caught, not raised).
        try:
            raise ValueError(f"smoke[{run_id}]: intentional smoke-test exception")
        except ValueError as exc:
            capture_exception(exc, context={"stage": "smoke", "smoke_run": run_id})

    sentry_sdk.flush(timeout=10)
    logger.info("sentry smoke: run {} complete — query Sentry for smoke_run={}", run_id, run_id)
    print(f"SMOKE_RUN_ID={run_id}")


if __name__ == "__main__":
    main()
