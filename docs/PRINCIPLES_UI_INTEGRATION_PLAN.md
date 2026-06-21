# Plan — your traceable principles on Derek's UI

**Status:** draft for review. No code written yet. Read-only investigation done
2026-06-21. Target branch to be confirmed (see §0).

Goal, in your words: every teammate runs the pipeline end-to-end on their own
data, lands in a **persisted, traceable** state, and Derek's UI references those
personal principles — clicking a principle/edge lets an agent query the DBs and
explain *why* it formed.

Simplified model (your decision, grounded in `docs/TIME_CAPSULE_FLYWHEEL.md`):

```
raw data ──▶ memories ──▶ principles ──▶ edges          (the built ladder — keep it)
   ▲                                        ▲
   └──────────── time capsules ─────────────┘
        capsules attach DIRECTLY to 1+ principles
        (no swarm / contradiction flywheel — cut for now)
```

So there are **two provenance kinds** meeting at the principle:
- **down** — principle → memory → raw event (why I believe it). *Already built.*
- **sideways** — capsule → principle (a moment that expresses it). *New, simple
  join; capsule does NOT rise through memory.*

---

## 0. Decision still open: which branch / who owns what

- **Target branch unconfirmed.** Derek's latest UI is `capsules-from-scratch`
  (the static `ui/` app). `nisa/feature-design` is newer overall. Confirm the
  integration target before touching anyone's branch.
- **This touches Derek's `ui/` and his principle data model.** §2/§4 change his
  files. Align with Derek first, or do the backend (§1, §3) on `aaryan-principles`
  and hand him a working endpoint to wire.

---

## 1. What already exists (no work)

- **The ladder, persisted.** `scripts/load_principles_db.py` (committed,
  `4c1f450`) folds `principles.json` / `edges.json` / `bank_snapshot.json` into
  `recall.db` tables: `principles`, `edges`, `memories`, `principle_memories`,
  `edge_memories`, `memory_events` → `events`. Verified: a single SQL join walks
  principle → memory → raw row.
- **Derek's UI already has the interaction.** `ui/app.js` has `renderGraph()`
  (principle graph) and `tracePrinciple()` ("this principle was formed at: …").
  Today both read `SEED` and trace to **capsules**. We're swapping the data
  source and adding the raw-data trace — not building the UX from scratch.
- **`recall.db` already has a `capsules` table** (`id, created_at, place_name,
  lat, lng`) + `media`. Currently 0 rows.

## 2. The three gaps (the actual work)

### Gap A — bootstrap stops at `principles.json`
`scripts/bootstrap.sh` runs build → retain → mint → show, but NOT `dump_bank.py`,
`link_principles.py`, or `load_principles_db.py`. So a teammate ends with
principles JSON but **no traceable `recall.db`**. Without this, "every teammate
goes end-to-end and it's persisted + traceable" is not reached.

### Gap B — the UI's principle shape was never served
Derek's UI models principles as `{id, label, text, capsules:[...]}` + edges
`{a, b, type}` (in `seed.js`), but the only backend (`poc_demo`) serves
`{name, content}` from Hindsight's `list_mental_models` — a *different* set of
principles with no IDs and no trace. So UI principles are **100% hardcoded seed**;
the backend wiring for principles was never finished, and it points at the
non-traceable source anyway.

### Gap C — no capsule → principle link
The simplified model needs capsules to attach to principles. No such table or
field exists yet. The UI's `seed.js` fakes it (`principle.capsules:[capsuleId]`).

---

## 3. Proposed work

### Step 1 — finish the per-teammate pipeline (Gap A) · `aaryan-principles`
Append to `scripts/bootstrap.sh`, after mint:
```
dump_bank.py          → data/bank_snapshot.json   (memory → raw_events)
link_principles.py    → data/edges.json           (principle ↔ principle)
load_principles_db.py → recall.db tables           (the persisted ladder)
```
Result: one `bash scripts/bootstrap.sh` leaves each teammate with a populated,
traceable `recall.db`. This is the highest-leverage change — it's what makes the
whole team reproducible. ~15 lines of bash, reuses existing scripts.

### Step 2 — capsule ↔ principle join (Gap C) · `aaryan-principles`
Add to `recall.db` (new table, additive, owned by the loader pattern):
```sql
CREATE TABLE principle_capsules (
    principle_id  TEXT REFERENCES principles(id) ON DELETE CASCADE,
    capsule_id    TEXT REFERENCES capsules(id)   ON DELETE CASCADE,
    PRIMARY KEY (principle_id, capsule_id)
);
```
Capsule does not rise through memory — this is a direct, user-asserted edge
(§3 of the flywheel doc: capsule as durable evidence node citing a principle).
Population path TBD (UI compose flow, or a script); for the demo it can be seeded.

### Step 3 — a backend that serves YOUR principles from `recall.db` (Gap B)
A small read-only API over `recall.db` (decision pending: new minimal FastAPI app
vs. reuse `poc_demo` server — you called `poc_demo` useless, so lean new). Routes:

| Route | Returns |
|---|---|
| `GET /api/principles` | `[{id, text, confidence, capsules:[capsule_id...]}]` — UI-shaped, from `recall.db` |
| `GET /api/edges` | `[{src, dst, relation}]` from the `edges` table |
| `GET /api/principles/{id}/trace` | the full down-ladder: `{principle, memories:[{memory_id, text, raw_events:[{id, source, content, t_utc}]}]}` |
| `GET /api/edges/{id}/trace` | edge → its `derived_from` memories → raw events |

`/trace` is the **agent's data surface**: it hands back the raw IDs at each layer
so the agent (runtime TBD) can query further itself, rather than baking an answer.
All pure SQL over `recall.db` — no Hindsight boot, no OpenRouter.

### Step 4 — point Derek's `ui/` at the real data (Gap B) · Derek's branch
In `ui/`:
- `api.js`: add `principles()` / `edges()` / `trace(id)` fetchers (mirror the
  existing `networks()` pattern; same `base()` + token handling).
- `app.js`: `renderGraph()` reads `/api/principles` + `/api/edges` instead of
  `SEED.principles`; `tracePrinciple()` calls `/api/principles/{id}/trace` and
  shows the raw-data chain (and still lights up linked capsules on the map via
  `principle_capsules`). Keep `seed.js` as the offline fallback.

### Step 5 (later, separate) — the explain agent
Once `/trace` exists, the agent gets tools to hit it (+ optionally query
`recall.db` directly) and explain why a principle/edge formed, citing raw rows.
Runtime shape deliberately deferred per your earlier call.

---

## 4. Open decisions for you / the team

1. **Target branch** (§0) — confirm before editing Derek's files.
2. **Backend home** — new minimal `recall.db`-only app, or swap `poc_demo`'s
   principle source. (Leaning new, given "poc_demo is useless".)
3. **How capsules get linked to principles** — manual/seed for the demo, or a
   real UI compose action. Step 2 builds the table either way.
4. **Re-run to a full bank first?** Current `recall.db` is the claude-only partial
   from the timed-out run (HANDOFF bug, now fixed). Everything above works on it,
   but principles are claude-only until retain is re-run on all 4 sources.

## 5. Suggested order
1. Step 1 (bootstrap) — unblocks the whole team, lowest risk, your branch.
2. Step 2 (capsule join) — additive schema, your branch.
3. Step 3 (backend) — your branch; hand Derek a working endpoint.
4. Step 4 (UI wiring) — Derek's branch, with him.
5. Step 5 (agent) — after the trace surface is live.
