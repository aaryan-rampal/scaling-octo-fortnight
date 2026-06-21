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

### Rung ③ output — `Principle` node (defined here for reference; NOT built yet)
Principles are **graph nodes**, not a flat list. Each node cites its supporting
memories (the ledger); edges between nodes are rung ④.
```python
@dataclass(frozen=True, slots=True)
class Principle:
    principle_id: str         # stable id, so edges can reference it
    text: str                 # the one-line mental model
    confidence: float         # 0..1, from the ledger (see rung③ research)
    derived_from: list[str]   # >=2 supporting memory_ids (the ledger)
```

### Rung ④ output — `Edge` (principle ⇄ principle, grounded; NOT built yet)
The principle layer is a **graph**: typed edges connect principles, and **each
edge carries its own evidence**, traced to memory-network nodes → raw_data like
everything else. An edge's evidence is **NOT** restricted to the intersection (or
union, or complement) of the two principles' ledgers — it is drawn from a
**soft-scope neighborhood** of the bank, so an edge can cite a memory neither
principle cites (e.g. a photo that co-occurs in time with both, linking them).
```python
Relation = Literal["supports", "refines", "generalizes", "contradicts"]

@dataclass(frozen=True, slots=True)
class Edge:
    src: str                  # Principle.principle_id
    dst: str                  # Principle.principle_id
    relation: Relation        # typed
    derived_from: list[str]   # >=1 memory_ids justifying the relation (the edge ledger)
```

**Edge candidate-evidence neighborhood** (computed from proximity in the
**Hindsight memory layer**, NOT from the ledgers, and NOT from raw_data): a
**memory** `m` (a Hindsight memory node) is in-scope for `edge(A, B)` iff
- `m`'s timestamp is within a time window of A's-or-B's supporting memories
  (temporal), **OR**
- `m` is embedding-similar to A or B via Hindsight `recall` (similarity).

Layer discipline (pipelinic): rung ④ operates **entirely over the memory layer**
— memory timestamps and memory embeddings. It never queries raw Events directly.
Hindsight owns raw_data → memories; we own memories → principles/edges. Raw_data
stays reachable only **through** a memory's `derived_from` chain (memory → unit →
raw Event), so the trace still bottoms out at raw_data without rung ④ ever
reading it.

The two principles' own evidence trivially lands in this neighborhood (near
itself), so shared evidence is allowed but not required; far-away unrelated
memories are excluded — which keeps the set **bounded and script-verifiable**.

**Edge verification rule (rung-spanning):** reject any cited `memory_id` not in
the edge's neighborhood (non-LLM script check). This is the bound that survives
reaching past the ledgers. Honest labeling: an edge that passes is **grounded**
(cites real in-scope memories), **not** "verified-entailing" — existence/scope ≠
entailment. An NLI entailment verifier is the post-v0 upgrade. Same `derived_from`
fail-fast applies: empty list rejected at write time.

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
