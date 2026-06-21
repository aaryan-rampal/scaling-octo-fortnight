# v0 raw→principles pipeline — interface contract

**Authoritative for the v0 build.** Three teammates build disjoint rungs in
parallel; this file is the shared contract so their worktrees don't drift. If a
teammate needs to change a shape defined here, message the lead — do not change
it unilaterally.

Scope: the **last-7-days slice** of `data/recall.db` (≈389 events: spotify 218,
imessage 143, photos 28; zero claude in this window). Build + unit-test only —
no live Hindsight retain during the build. The real run happens when the lead
orchestrates the assembled pipeline.

Decided forks (do not relitigate):
- Segmentation = per-source **inactivity-gap**, zero LLM. No topic/semantic.
- Cross-source entity canonicalization = **out of scope**.
- The agentic swarm (retriever/critic/arbiter) + contradiction loop = **out of scope**.
- Rung ③ minting = a plain consolidation pass that writes principles with an
  evidence ledger. Its internal strategy (cluster-first vs global) is an OPEN
  research question owned by `research-minting` — do not implement ③ yet.

---

## The shapes (the only cross-rung interface)

### Input — canonical `Event` (already on disk, `src/core/schema.py`)
Frozen dataclass: `id, t_utc, author_role, content, thread_id, reply_to,
raw_ref, source, additional_data`. Read the 7-day slice from the unified
`events` table via `storage.store.CapsuleStore.list_events(...)` (read-only).

> **DB reads: use Python `sqlite3`, not the `sqlite3` CLI** — the CLI hangs in
> this shell environment. `sqlite3.connect("file:data/recall.db?mode=ro", uri=True)`.

### Rung ① output — `Unit` (NEW, owned by builder-segment)
A unit is one coherent run handed to a single rung-② `retain`/render call.

```python
@dataclass(frozen=True, slots=True)
class Unit:
    unit_id: str            # stable hash of (source, thread_id, t_start, t_end)
    source: str             # "imessage" | "spotify" | "photos" | ...
    derived_from: list[str] # NON-EMPTY list of Event.id values, in time order
    t_start: datetime
    t_end: datetime
```

Provenance rule (rung-spanning, non-negotiable): **`derived_from` is a non-empty
LIST**; reject an empty list at construction time (fail fast). A scalar ref is
forbidden — non-contiguous merges would silently drop sources.

### Rung ② output — what `retain` stores + a local `Memory` ref row
Rung ② renders each `Unit` → text, calls Hindsight `retain`, and records the
mapping so rung ③ can trace a memory back to its unit:

```python
@dataclass(frozen=True, slots=True)
class MemoryRef:
    memory_id: str          # Hindsight-returned id for the retained memory
    derived_from: list[str] # the Unit.unit_id(s) it came from (non-empty)
```

### Rung ③ output — `Principle` (defined here for reference; NOT built yet)
```python
@dataclass(frozen=True, slots=True)
class Principle:
    text: str                 # the one-line mental model
    confidence: float         # 0..1, nudged ±alpha by evidence
    derived_from: list[str]   # >=2 supporting memory_ids (the ledger)
```

---

## Rung ① — builder-segment

**Owns:** `src/pipeline/segment.py` (new) + `tests/pipeline/test_segment.py`.
**Must NOT touch:** render/retain files (rung ②), `core/schema.py`, `storage/`.

> **Do NOT read or use `src/pipeline/episodes.py`** — it is outdated and must
> not inform this build. `docs/raw-to-principles-research.md` is the sole
> authority for rung behavior. Build rung ① fresh from §1 of that doc.

Behavior:
- Read events for the 7-day slice. Group **per source**:
  - conversational (imessage, claude): group by `thread_id`, order by `t_utc`,
    cut when gap between consecutive events **> T** (default T=30 min; make it a
    parameter). A gap of exactly T keeps both in the same unit.
  - non-conversational (spotify, photos): per-source activity runs on `t_utc`
    gap (same T). No thread_id.
- Emit `Unit`s with a non-empty `derived_from` list of the contained `Event.id`s.
- Zero LLM, no network.

Acceptance: fixtures-only pytest. Cover: a single-thread split on a > T gap; an
exactly-T gap that does NOT split; a non-conversational run; empty input → [].

## Rung ② — builder-extract

**Owns:** `src/pipeline/render.py` (new, unit→text) + the retain wrapper +
`tests/pipeline/test_render.py`.
**Must NOT touch:** segment.py (rung ①), `runtime/hindsight.py` (read it, don't
edit), `core/`, `storage/`.

Behavior:
- `render_unit(unit, events) -> str`:
  - conversational: pass the transcript through (role-prefixed lines), in order.
  - spotify: templated fact per play from `additional_data`
    ("On {t}, listened to {track} by {artist}").
  - photos: templated fact from `additional_data`
    ("On {t}, photo at {place/geo} with {people}"), people may be empty.
- A retain wrapper that takes rendered text + the unit's `derived_from`, calls
  Hindsight `retain`, and returns a `MemoryRef`. Pass `author_role` through so
  self→Experience / others→World routes (see research doc §2). **Do not run it
  live** — unit-test the renderer with fixtures; the retain call is exercised
  only when the lead runs the assembled pipeline. Use the embedded client from
  `runtime.hindsight.embedded_hindsight` (read its signature; don't modify it).

Acceptance: fixtures-only pytest on `render_unit` for all three source kinds;
the retain wrapper is structurally tested with a fake client (no network).

## research-minting (rung ③ strategy — RESEARCH, not code)

**Owns:** `docs/` (a new research doc). **Must NOT touch any `src/`.**
See its own brief. Output: a doc recommending the minting strategy
(cluster-first vs single global call vs other), grounded in the same literature
the research doc §3 cites (Generative Agents reflection tree, etc.), with a
clear v0 recommendation the lead can pick from.

---

## Build notes (verified against the real DB — supersede earlier assumptions)
- **Spotify renders from `Event.content`, not `additional_data`.** Verified: in
  `data/recall.db`, spotify rows have `additional_data == {}` and the track/
  artist/album live in `content` (built by `SpotifyStreamRecord.content_line()`).
  Photos DO carry geo/people in `additional_data` as the contract states.
- **Hindsight `retain` returns no bare `memory_id`.** `RetainResponse` exposes
  `success / items_count / operation_id / operation_ids / usage`. Rung ② sets
  `MemoryRef.memory_id` from `operation_id`. **Rung ③ caveat:** if the evidence
  ledger needs a true per-memory id (to quote/trace a single memory), resolve it
  post-retain from the operation — do not assume `memory_id` is already a memory.
- Network routing is made explicit via tags/metadata (`network:experience|world`)
  from `author_role`, since Hindsight leaves multi-participant routing implicit.

## Integration (lead does this, after teammates return)
1. Review each summary; check no cross-worktree file overlap.
2. Run full `pytest -q` on the merged tree.
3. Pick a minting strategy from research-minting's doc; THEN build rung ③.
4. Orchestrate one live run over the 7-day slice (Doppler injects
   `OPENROUTER_API_KEY`): segment → render+retain → mint → print principles +
   their evidence (memory_ids/quotes).
