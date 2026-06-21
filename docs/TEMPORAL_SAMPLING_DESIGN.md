# Design — temporal-spread sampling (90-day reach, ~30-day cost)

**Status:** design for review. No code yet. Read-only investigation 2026-06-21.
Lives upstream in segmentation; does NOT touch the principle/edge/link layer.

## Problem

Retain consumes a contiguous recent window (7d / 30d). The trade-off is bad at
both ends:

- **7d** — cheap but shallow; no temporal reach, can't see patterns spanning months.
- **30d contiguous** — more data, still only one month of reach, and dominated by
  whatever recent block is densest.

A contiguous window also can't tell a one-off intense week from a habit that
recurs every few weeks — and recurrence across time is exactly what promotes a
principle from provisional to durable (flywheel §9).

## Idea

Take **90 days of reach** at **~30 days of cost** by thinning the span instead of
truncating it. Slice the 90d into intervals, keep a quota of units from each,
drop the overflow. Reach = 90d; volume ≈ 30d; coverage is even instead of
recency-dominated.

## Cost reality (measured, settles the approach)

| Step | Cost | Note |
|---|---|---|
| ingest: iMessage / Claude | none | pure parsing |
| ingest: photo vision / Spotify vibes | OpenRouter, **but cached** | `photo_vision_cache.json`, `artist_vibes.json` keyed by image/artist; re-ingest pays only for new items |
| **retain (Hindsight)** | **OpenRouter per unit** | gemini extract + qwen embed, 1 call/unit — **the expensive step** |

So: **a 90-day re-ingest is cheap; retain is what costs.** The sampler exists to
protect retain. Sampling itself (unit counts, spread) is verifiable for free
without running retain at all.

## Current data (why 90d looks like 30d today)

On the present `recall.db`, ingestion only reached ~34 days, so 90d == 30d == 119
units. Weekly distribution:

```
week 0 (0–6d):    70 units   imessage, spotify, photos   ← dense recent block
week 1 (7–13d):    8 units   spotify, photos
week 3 (21–27d):  33 units   claude only
week 4 (28–34d):   8 units   claude only
weeks 2, 5–12:     0 units
```

The sampler needs a real 90-day **ingest** first (cheap, per above) or it thins an
empty tail. Week 0's 70 units — more than half of everything — is exactly the
recency spike a weekly quota flattens.

## Decisions (locked)

- **Shape:** per-window quota. Even temporal coverage regardless of burstiness.
- **Interval:** **weekly** (~13 buckets over 90d). Matches the weekly burstiness;
  natural human cadence; not as over-thinning as daily.
- **Quality gate:** **iMessage-only** minimum-message threshold, applied **before**
  the quota — drop thin/spam conversations. Non-chat sources (spotify/photos/
  claude) are not conversations, so the count is meaningless there and they pass
  through ungated.
- **Volume target:** K (units/week) chosen so total units ≈ a 30-day run (~119);
  exact K set after seeing weekly counts on the real 90-day ingest.

## Algorithm

```
segment all 90d events → units              (existing segment_events)
  → iMessage gate:  drop units where source=="imessage" and
                    len(derived_from) < MIN_IMESSAGE_MSGS         (filter)
  → weekly quota:   bucket remaining units by week(t_end);
                    within each bucket keep the top K              (cap)
  → flatten buckets back to a time-ordered unit list → retain
```

Open sub-decision (call it in review): **which K units to keep per bucket** when a
bucket exceeds K. Candidates: largest units (most `derived_from`), or evenly
strided across the bucket. Largest-first biases toward substantive runs; strided
preserves intra-week spread. Lean **largest-first** (substance over uniformity
within a single week).

## Placement (keeps clear of relation/edge work)

New function in `src/pipeline/segment.py`, alongside `segment_recent`:

```python
def segment_windowed_quota(
    db_path: str | None = None,
    gap: timedelta = DEFAULT_GAP,
    span: timedelta = timedelta(days=90),
    interval: timedelta = timedelta(days=7),
    per_interval: int = ...,          # K, the weekly cap
    min_imessage_msgs: int = 20,      # the iMessage gate
) -> list[Unit]:
    ...
```

`retain_slice.py` opts in via a flag (e.g. `--quota K --span-days 90`), choosing
`segment_windowed_quota` over `segment_recent` at the one call site
(`retain_slice.py:143`). `segment_recent` and everything downstream — including
the link/edge code — are untouched.

Reuses existing primitives: `segment_events` (the gap sessionizer),
`Unit.derived_from` / `Unit.source` / `Unit.t_end` (already on the dataclass). The
provenance invariant (every Unit keeps its non-empty `derived_from`) is preserved
— sampling only drops whole units, never reshapes them, so the
unit→raw-event chain stays intact for the principles that survive.

## The same mechanism powers the "top conversations" ask

The iMessage "take all convos in last N days, filter spam (min messages), spread
them" request is **this exact pipeline** — the min-message gate is the spam
filter, the weekly quota is the spread. One mechanism, not a second system.

## Verification path (no double spend)

1. **Re-ingest 90 days** (cheap; cached enrichment) → `recall.db` spans 90d.
2. **Build sampler + gate**, run it, inspect unit counts + weekly spread. **Free —
   no retain, no network.** This is where K and the gate threshold get tuned.
3. **Run retain once** on the sampled units → the one real cost, bounded to
   ~30-day budget but with 90-day reach. (Doubles as the full-bank re-run the
   HANDOFF already owes.)

## Out of scope / dependencies

- 90-day **ingest** is a build-window change (`--<src>-days`), a prerequisite, not
  part of the sampler itself.
- Recency-weighting (thin old weeks harder than recent) is deliberately NOT done —
  flat weekly quota first; weighting is a later knob if the flat version
  over-represents quiet weeks.
- Worktree workflow: this ships in its own worktree; final merge + run + verify
  happens at the end across all worktrees.
