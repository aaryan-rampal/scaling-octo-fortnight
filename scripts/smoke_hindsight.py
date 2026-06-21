"""Smoke test: retain one memory then recall it through embedded Hindsight.

Run with: doppler run -- .venv/bin/python scripts/smoke_hindsight.py
Exits 0 on a successful retain + recall round-trip.
"""

from __future__ import annotations

import sys

from runtime.hindsight import embedded_hindsight

BANK = "smoke-test"
CONTENT = "Aaryan is testing the recall pipeline"
QUERY = "what is Aaryan doing?"


def main() -> int:
    with embedded_hindsight() as client:
        client.create_bank(BANK)

        retain_resp = client.retain(bank_id=BANK, content=CONTENT)
        print("RETAIN:", retain_resp.model_dump())

        recall_resp = client.recall(bank_id=BANK, query=QUERY)
        print(f"RECALL ({len(recall_resp.results)} result(s)):")
        for result in recall_resp.results:
            print(f"  - [{result.type}] {result.text}")

        if not recall_resp.results:
            print("FAIL: recall returned no results", file=sys.stderr)
            return 1

    print("OK: retain + recall round-trip succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
