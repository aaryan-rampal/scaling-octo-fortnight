# EDA findings — retained memory bank (`data/bank_snapshot.json`)

84 memories retained from the user's last-7-days slice (iMessage / Spotify /
photos), the output of the v0 pipeline (raw → segment → render → Hindsight
retain). This is the layer principle-minting (rung ③/④) will be built on.

Reproduce: `PYTHONPATH=src .venv/bin/python scripts/eda_bank.py`

---

## 1. Distribution

| source | memories | share |
|---|---|---|
| imessage | 43 | 51% |
| spotify | 23 | 27% |
| photos | 18 | 21% |

- **raw_event fan-out (1:N):** mean 6.1, min 1, max 44. 20 memories (24%) are
  backed by a single raw event; the long tail (35–44 events) is bundled Spotify
  listening runs.
- **fact_type:** `experience` 65, `world` 19. All 19 `world` facts are iMessage.
- **entities:** 119 distinct. `user` appears on 63 of 84 memories (noise for
  clustering). The next tier is Spotify artist names (`calvin harris` 9,
  `don toliver` 6, `drake`/`michael jackson`/`bts` 4) — high frequency, low
  reuse across sources.

## 2. Spotify-skew — verdict: **YES, but not via the obvious metric**

| source | n | avg text len | avg entities | avg *specific* entities | fact_types |
|---|---|---|---|---|---|
| imessage | 43 | 171.3 | 2.19 | 1.28 | world 19, experience 24 |
| spotify | 23 | 217.7 | 6.22 | 5.22 | experience 23 |
| photos | 18 | 112.9 | 1.17 | **0.00** | experience 18 |

Spotify memories look "rich" by raw text length and entity count, but that is an
artifact: long text = bundled song *sequences*, high entity count = artist/track
names. The semantic payload per memory is a single shallow predicate —
"listened to X." Confirming this:

- **Fact diversity:** Spotify and photos are **100% `experience`**; only iMessage
  yields standing `world` facts. There is exactly one behavioral predicate per
  non-message source (listened / took-photo).
- **Photos are the shallowest:** **0.00 specific entities** — their only entities
  are GPS coordinates and `photo`/`user`.

**Implication:** minting needs a per-source importance gate. A naive volume gate
would let Spotify dominate (27% of the bank, one predicate) and mint
"listens-to-X" pseudo-principles. Down-weight single-predicate `experience`
memories; let iMessage `world`/`experience` carry the behavioral signal.

## 3. Clustering preview — **56% singletons; cross-source moments need TIME, not entities**

Clustering by **shared specific entity** (excluding `user`, `photo`, coordinates;
no temporal chaining, which otherwise transitively merges the whole 7-day window
into one blob):

- **53 clusters; 47 singletons (56%)** — would be dropped, since a principle
  needs ≥2 supporting memories.
- **6 mintable clusters (≥2).** The real ones are person-centered iMessage
  threads: `marleif` (3), `justin cho` (3), an unnamed `user's friend` (5),
  `claude code` (2). One Spotify pair shares `olivia dean`.
- **The n=22 "cross-source" cluster is a false positive:** 19 spotify + 3
  imessage with an **empty bridge-entity set** — they are chained only by the
  coincidental shared token `notion` (an app), not a shared moment.

**Entity clustering cannot find cross-source moments here:**

- Photos carry **zero non-coordinate entities** → they can *never* join an entity
  cluster. Structurally isolated.
- Spotify↔iMessage share exactly one entity (`notion`), which is coincidental.

**Temporal proximity is the only bridge that reaches photos and Spotify.**
Pairwise co-occurrence within 60 min finds genuine cross-source pairs:

| pair | count (≤60 min) |
|---|---|
| imessage ↔ spotify | 7 |
| photos ↔ spotify | 6 |
| imessage ↔ photos | 4 |

These are the candidate "moments" (a photo + the song playing + the text about
it). They surface by **time**, not entity.

**Implication for rung 3/4:** entity-only clustering yields ~6 mostly
single-source clusters and discards 56% of the bank. To find the cross-source
moments the product promises, the neighborhood definition **must include the
temporal window** (which the contract already specifies for rung ④ edge scope).
Without it, photos contribute nothing and Spotify only self-clusters.

## 4. Provenance sanity — **clean**

- **0 / 84 memories have an empty `raw_events` chain.** All 84 trace to ≥1
  ground-truth row.
- Highest unsupported-token ratios are not hallucinations:
  - Photos top the list because the renderer adds date/template vocabulary
    ("Saturday", "June", "rapid succession") absent from raw content.
  - The highest-ratio iMessage cases are legitimate LLM *summarization* of a
    conversation (e.g. "feeling sad because they were not meshing well with
    someone"), where the extracted fact paraphrases rather than copies the raw
    text. Reviewed — paraphrase, not fabrication. No memory asserts an entity or
    event absent from its raw events.

No hallucinations found.

## 5. Surprises worth knowing before minting

- **23 of 43 iMessage memories have no `occurred_start`.** These are the `world`
  facts (relationships, attributes). They are invisible to any time-window join,
  so the strongest cross-source bridge (temporal) cannot reach exactly the
  memories that carry standing facts. Mitigation: fall back to the memory's
  `raw_events[].t_utc` for a timestamp when `occurred_start` is null.
- **19 `world` facts are standing facts, not behavior** ("user has a brother,"
  "Justin Cho's email is …"). Behavioral-corroboration gating (rung ③) should
  **not** count `world` facts as behavioral evidence — they are context, not
  repeated action.

---

## Implications for principle-minting (summary)

1. **Per-source importance gate is required.** Spotify is shallow-but-voluminous
   (one predicate, 27% of bank); without a gate it dominates and mints
   listens-to-X non-principles. Down-weight single-predicate `experience`.
2. **Neighborhoods must be temporal, not entity-only.** Entity clustering drops
   56% of memories and isolates photos entirely. The cross-source moments — the
   product's headline — exist only in the time dimension.
3. **Backfill timestamps from `raw_events`.** Half of iMessage (incl. all `world`
   facts) lack `occurred_start`; without backfill they are invisible to temporal
   joins.
4. **Separate `world` from `experience` in the ledger.** `world` = context for
   confidence/framing; `experience` = the behavioral evidence that corroborates a
   principle. Do not let restated `world` facts inflate corroboration counts.
5. **Provenance is sound** — build minting on it without remediation; all 84
   memories trace cleanly to raw events, no hallucinations.
