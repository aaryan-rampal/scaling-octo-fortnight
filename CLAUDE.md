# Recall / RETURN — agent seed

Authoritative orientation for any agent working in this repo. Read this before
touching code. It tells you **what we're building**, **what actually exists vs.
what's vision**, **the stack and how to run it**, and **the few rules that keep
the design honest**. When a fact here conflicts with what's on disk, trust the
disk and flag the drift.

---

## 1. What this is

A **single-user personal memory + principles tracker**. We ingest a person's own
data (iMessage runs end-to-end; photos / Spotify / Claude-chat exports have real
adapters that emit canonical events + persist, but aren't wired into the
pipeline yet — see §3), fold it into memory networks via
[Hindsight](https://github.com/vectorize-io/hindsight) (episodic / semantic /
entity / **principles**), and surface non-obvious, **traceable** insights about
how that person thinks and behaves.

Two names in the repo, same project:
- **Recall** — the shipped POC / distribution name (`src/` packages, `recall` CLI).
- **RETURN** — the hackathon product framing (location-tagged "time capsules"
  you seal at a place and revisit on return). Working title; not final.

**The flagship, user-facing concept is the _principle_** — a short, one-line
mental model ("keep weekends free, unless close friends"). Memory networks
(episodic/semantic/entity) stay backend; only principles and synthesized
connections surface to the user. Reflection is **conversational, not
recommendation** ("Do you remember when X?") to preserve user agency.

**Single-player only.** No social / multi-user features — that's a separate
domain, explicitly out of scope.

---

## 2. The load-bearing idea: provenance is a property of the path

Everything traces back to ground truth. Data rises through a fixed ladder:

```
raw_data sources  →  segment+align  →  memory networks  →  consolidation  →  principles
(iMessage, photos,    (BB1: thread       (episodic /         (BB3: mint        (what the
 email, calendar,      into convos,       semantic /          beliefs from      user reads)
 journal text)         window, tag)       graph/entity)       memory)
```

A principle is traceable **because** it was consolidated from memories extracted
from source rows — each step leaves a link. There is no "attach provenance"
operation; provenance is the path, not a stamped field. The single rule that
keeps this true:

> **Principles are born/changed ONLY by consolidation reading raw_data up
> through memory.** Nothing writes a principle directly. When agents need to
> create a belief, they inject **high-priority raw_data** and let it rise — never
> write to the principle layer.

The full target architecture (the self-reinforcing "flywheel" where
contradictions route back to the user, whose answer becomes richer raw_data) is
in **`docs/TIME_CAPSULE_FLYWHEEL.md`**. Read it for the vision. But see §3 —
most of it is **not built**.

---

## 3. Reality check: POC vs. vision (do not confuse these)

The repo today is a **proof-of-concept**, not the flywheel. Be precise about
which layer you're touching.

| Capability | Status |
|---|---|
| iMessage ingest → events → episodes → Hindsight → show / web UI | **BUILT** — this is the POC, end to end |
| Four memory networks + `reflect` (synthesized connection) | **BUILT** (via Hindsight) |
| Time-capsule write path + SQLite store | **PARTIAL** — `src/core/capsule.py`, `src/storage/store.py`, `poc_demo/server/capsule*` exist |
| Photos / Spotify / Claude-chat adapters | **BUILT but not wired** — `src/adapters/*` parse the source → canonical `Event` → persist to the unified `events` table (tested), but nothing in the `recall` CLI / episodes→Hindsight flow calls them yet. Only Spotify has its own `python -m adapters.spotify` CLI |
| Unified events store (one source-agnostic `events` table) | **BUILT** — every adapter persists via `src/storage/persist.py` into one table in `src/storage/store.py` |
| Location geofence / "locked until you return" | **FAKED for the demo** — an "I'm back" button, not real GPS |
| The agentic swarm (retriever / critics / arbiter) | **NOT BUILT** — vision only |
| The consolidation flywheel + contradiction loop | **CUT for the hackathon** — "vision, not v1" |

If you're asked to "build the flywheel" or "add the swarm," confirm scope first —
that's north-star work, and the 24h hackathon build deliberately cut it. The
demo is **reconstruction-first** (photo/data in → reconstruct a moment +
principles), with the flywheel as the story we point at, not code we run.

---

## 4. Stack & layout

**Python 3.13** (backend/pipeline) + **Node 22 / pnpm** (web). Inference via
**OpenRouter**; secrets injected by **Doppler** (`berkeley-hackathon` / `dev`),
never stored in the repo.

`src/` is the package root (no umbrella package; imports are bare top-level,
e.g. `from adapters.spotify import ...`, `from core.schema import Event`). The
console script `recall` resolves to `cli:main`.

```
src/
  cli.py             `recall ingest|episodes|load|show|all`  (iMessage pipeline)
  core/              canonical domain types
    schema.py          Event / Episode (the universal currency every adapter emits)
    capsule.py         Capsule / Media (time-capsule write path)
  models/            per-source typed records (pydantic): spotify, imessage, photo, llm_export
  adapters/          per-source: raw source → models → Event
    imessage.py        chat.db (read-only) → events  (the wired source)
    spotify.py · photos.py · llm_chats.py   built, emit events + persist, not in CLI yet
  storage/
    store.py           CapsuleStore: the unified, source-agnostic `events` table + capsules
    persist.py         persist_events(): the single write path into that table
  pipeline/          transforms over Events, toward Hindsight
    episodes.py        temporal-window events → conversation episodes
    load.py            episodes → Hindsight (retain)         ← only step that costs LLM calls
    show.py            query the 4 networks + reflect
  runtime/
    hindsight.py       boot embedded Hindsight (pg0 + OpenRouter)
poc_demo/server/   FastAPI backend (boots embedded Hindsight, serves JSON)
poc_demo/web/      Vite + React + TypeScript frontend
ui/                static mobile web app ("recapsule") — on the ui-scaffold branch
docs/              TIME_CAPSULE_FLYWHEEL.md (north-star) + adapter / store design docs
context/           team transcripts, Q&A, design docs (decision history)
tests/             pytest mirroring src: tests/{core,models,adapters,storage,pipeline}/
```

- `chat.db` is read **read-only** — the pipeline never writes to Messages.
- Every source persists to **one unified `events` table** (source-agnostic via a
  `source` column; non-conversational sources like photos leave the
  conversational fields null and carry payload in `additional_data`).
- Loaded data persists in embedded Postgres (`pg0`) on disk, scoped to a bank id
  (default `imessage-v0`).
- Pipeline vocabulary (settled): **Event → Episode → Abstraction → Cluster →
  Connection → principle graph.** Use these terms (`Event` is the canonical
  per-message/per-item type in `core/schema.py`).

---

## 5. Running it

```bash
# Python env — symlinked as .venv per repo convention
uv venv ~/env/recall --python 3.13 && ln -s ~/env/recall .venv
uv pip install --python .venv/bin/python -e .

# Pipeline (Doppler injects OPENROUTER_API_KEY)
doppler run --project berkeley-hackathon --config dev -- recall all --top-n 5 --limit 150

# Web demo (two terminals)
doppler run --project berkeley-hackathon --config dev -- \
  .venv/bin/python -m uvicorn poc_demo.server.app:app --port 8000
cd poc_demo/web && pnpm dev          # → http://localhost:5173

# Tests (no network, fixtures)
.venv/bin/python -m pytest -q
```

`recall load` is the only step that spends OpenRouter calls (one extraction per
episode). `--limit 0` loads all episodes. Principles stay empty until enough
episodes load for Hindsight consolidation to form mental models.

---

## 6. Conventions

- Python: **uv / ruff / ty** (not pip/black/mypy). `ruff` line-length 100,
  target py313; lint set `E,F,I,B,UP,SIM,RUF`. `ty` rules in `pyproject.toml`.
- Tests in `tests/` mirroring package structure; fixture-based, no network.
- Web: TypeScript, ESM. (Repo currently uses eslint via `eslint.config.js`.)
- Secrets only via Doppler / env — never commit keys.
- Absolute imports; self-documenting code; fail fast with actionable errors.

---

## 7. Open forks (don't silently pick a side)

These were unresolved at last writing — decided at the Hour-0 whiteboard, may
still be live. If a task depends on one, surface it rather than assuming:

- **Memory engine** — Hindsight vs. Redis-native vs. both. POC uses Hindsight.
- **Hero interaction** — intentional capsule-creation-that-locks-until-return
  (team consensus) vs. photo-in reconstruction (the built demo). Not reconciled.
- **Crisis detection** — unowned, and the most serious gap. The app invites
  revisiting emotionally charged moments with no tripwire. Non-negotiable before
  running on anyone's real data.
- **Nostalgia guardrail** — reflection should end forward-looking, never "go back
  to how it was." A claim, not yet a mechanic.
- **Local vs. remote inference** — remote (OpenRouter) for now; local (Gemma) is
  north-star. Keep privacy claims honest: "local-first architecture,
  abstraction-only egress, remote inference in this build."

Full decision history and rationale: `context/team-questions-and-answers.md`.

---

## 8. How to behave here

- **Don't write principles directly. Don't fabricate provenance.** Inject
  raw_data and let it rise (§2). This is the one invariant that rots silently if
  you break it.
- **Keep POC and vision separate** (§3). Don't document or build flywheel/swarm
  pieces as if they exist.
- **Definition of done** (team-agreed): at least one non-obvious, grounded,
  traceable insight per person from their own data.
- **Read the design doc before architecture work**: `docs/TIME_CAPSULE_FLYWHEEL.md`.
