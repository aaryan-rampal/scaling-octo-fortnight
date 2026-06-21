# Principle trace-back + "why" agent — design doc

Owner: Selin · Status: design (no code yet) · Audience: you, first time doing backend

This is the read path for the flagship interaction: **a user clicks a principle,
and we instantly show the full chain of evidence behind it plus a short,
LLM-written explanation of _why_ that principle exists.** Nothing here writes
principles or touches Hindsight at runtime — it only *reads* the provenance graph
Aaryan already materialised and *explains* it.

---

## 0. What "backend" means for this task (don't panic)

You're not building a distributed system. For this feature, "backend" is just
three boring, testable layers:

1. **Read from a database** — run some SQL against a SQLite file, get Python
   objects back. (SQLite = a whole database that lives in a single `.db` file.
   No server to install; Python's built-in `sqlite3` opens it.)
2. **Call an LLM** — send the evidence to OpenRouter, get text back. (Same
   pattern already used in `src/pipeline/link.py` — you can copy it.)
3. **Expose it** — a CLI command (and optionally an HTTP endpoint) so someone
   can hand in a principle id and get the answer.

That's the whole job. Each layer is a plain function. You can build and test
layer 1 with zero network and zero API keys.

---

## 1. The data you're reading (already built — you do NOT build this)

Aaryan materialised the full provenance graph into **SQLite**. Two files, same
schema:

- `data/recall.db` — the real graph (153k events).
- `data/derek_handoff/derek_sample.db` — a tiny, fully-traceable 5-principle
  slice. **Develop and test against this.** It has zero dangling ids, so every
  query returns real data.

> ⚠️ Reality check: in *this* worktree, `recall.db` currently only has
> `events` / `capsules` / `media`, and `derek_handoff/` isn't here yet — those
> are on Aaryan's branch. **Before you run anything**, get the real DB:
> `git pull` Aaryan's principle tables, or just copy `derek_sample.db` into
> `data/derek_handoff/`. Your code targets the schema below regardless; only the
> file needs to show up.

### The tables you'll touch

| layer | table | key columns |
|---|---|---|
| user-facing | `principles` | `id`, `text`, `confidence` |
| user-facing | `edges` | `id`, `src_principle_id`, `dst_principle_id`, `relation` |
| synthesised | `memories` | `memory_id`, `text`, `source`, `occurred_start`, `fact_type`, `entities` |
| raw truth | `events` | `id`, `t_utc`, `author_role`, `content`, `raw_ref`, `source` |
| wiring | `principle_memories` | `principle_id`, `memory_id` |
| wiring | `edge_memories` | `edge_id`, `memory_id` |
| wiring | `memory_events` | `memory_id`, `event_id` |

### The trace ladder (this IS the "instant trace back")

```
principle ──principle_memories──▶ memories ──memory_events──▶ events (raw ground truth)
edge      ──edge_memories──────▶ memories ──memory_events──▶ events
```

Full SQL reference lives in Aaryan's `data/derek_handoff/SCHEMA.md`. The one
query that does the whole principle→raw walk:

```sql
SELECT m.memory_id, m.text AS memory, m.source, m.occurred_start,
       e.id AS event_id, e.t_utc, e.author_role, e.content, e.raw_ref
FROM principle_memories pm
JOIN memories m       ON m.memory_id = pm.memory_id
JOIN memory_events me ON me.memory_id = m.memory_id
JOIN events e         ON e.id         = me.event_id
WHERE pm.principle_id = :principle_id
ORDER BY m.occurred_start, e.t_utc;
```

---

## 2. What we're building

A function `explain_principle(principle_id)` that returns:

```jsonc
{
  "principle": { "id": "...", "text": "You make deliberate ...", "confidence": 0.7 },
  "memories": [
    { "memory_id": "...", "text": "The user analyzed a vaccine ...", "source": "claude",
      "occurred_start": "2025-...",
      "events": [
        { "id": "...", "t_utc": "2025-...", "author_role": "self",
          "content": "...", "raw_ref": "claude:<conv>#<msg>" }
      ]
    }
  ],
  "why": "This principle surfaced because, across N conversations in <date range>, you repeatedly ..."
}
```

- `principle` + `memories[].events` = the **trace** (deterministic, from SQL).
- `why` = the **agent's** grounded summary (the one LLM call).

The UI can show the trace as a click-through tree *and* the `why` paragraph.

---

## 3. File plan (where each piece goes)

Following the repo's layout (`src/` is the package root; storage code in
`src/storage/`, pipeline/LLM code in `src/pipeline/`):

| file | new? | responsibility |
|---|---|---|
| `src/storage/trace.py` | **new** | Pure DB reads. Open the SQLite file, run the ladder queries, return dataclasses. No network. |
| `src/pipeline/explain.py` | **new** | The agent. Takes a trace, builds the prompt, calls the LLM behind an injectable seam, returns `why`. Plus the top-level `explain_principle()` that wires trace → agent. |
| `src/cli.py` | edit | Add an `explain` subcommand: `recall explain <principle_id>`. |
| `tests/storage/test_trace.py` | **new** | Offline test against `derek_sample.db` — no network. |
| `tests/pipeline/test_explain.py` | **new** | Fake-LLM test of the agent + assembly. |
| `poc_demo/server/app.py` | edit (optional, phase 2) | `GET /principles/{id}/why` endpoint for the frontend. |

### 3a. `src/storage/trace.py` — the read layer

Small read-model dataclasses (don't reuse `core.principle.Principle`; that one
enforces ≥2 supports and is built for the *write* path — overkill for read):

```python
@dataclass(frozen=True, slots=True)
class TracedEvent:
    id: str; t_utc: str; author_role: str; content: str; raw_ref: str; source: str

@dataclass(frozen=True, slots=True)
class TracedMemory:
    memory_id: str; text: str; source: str; occurred_start: str | None
    events: list[TracedEvent]

@dataclass(frozen=True, slots=True)
class PrincipleTrace:
    principle_id: str; text: str; confidence: float
    memories: list[TracedMemory]
```

Functions (all take an open `sqlite3.Connection` so tests can pass a fixture DB):

```python
def open_db(path: str | Path) -> sqlite3.Connection: ...   # sets row_factory = sqlite3.Row
def get_principle(conn, principle_id) -> PrincipleTrace | None  # principle row only
def trace_principle(conn, principle_id) -> PrincipleTrace | None  # full ladder, nested
def trace_edge(conn, edge_id) -> ... # phase 2: the edge variant of the ladder
```

`trace_principle` runs the §1 join, then groups the flat rows by `memory_id` into
the nested shape. **Read-only**: never `INSERT`/`UPDATE` — this layer only
surfaces the path that already exists.

Edge cases to handle (so the CLI never crashes on bad input):
- principle id not found → return `None` (CLI prints a friendly message).
- principle exists but has 0 memories, or memories with 0 events → return the
  trace with empty lists; the agent should say "thin evidence" rather than invent.

### 3b. `src/pipeline/explain.py` — the agent

Copy the LLM seam pattern from `link.py` (`LLMEdgeProposer`): a `Protocol` for the
stochastic step + a live OpenRouter implementation, so tests inject a fake and run
without a key.

```python
class WhyExplainer(Protocol):
    def explain(self, trace: PrincipleTrace) -> str: ...

class LLMWhyExplainer:               # live: OpenRouter via the openai client
    def __init__(self, api_key=None, model="google/gemini-3.5-flash"): ...
    def explain(self, trace) -> str: ...

def explain_principle(conn, principle_id, explainer) -> dict | None:
    trace = trace_principle(conn, principle_id)
    if trace is None: return None
    why = explainer.explain(trace)
    return {"principle": ..., "memories": ..., "why": why}
```

**Prompt design** (the actual product surface — get this right):
- System role: "You explain *why* a personal principle was inferred, grounded
  ONLY in the evidence given. Cite specific moments. Never invent events."
- User content: the principle text + confidence, then each memory with its raw
  events (content, date, author, `raw_ref`) laid out underneath.
- Honour the repo's tone rules (CLAUDE.md §1): **conversational, not
  recommendation** ("This showed up because you kept…"), and **end
  forward-looking**, never "go back to how it was."
- If evidence is thin/empty, say so honestly instead of fabricating confidence.

Why an injectable seam? So `tests/pipeline/test_explain.py` can pass a
`FakeExplainer` that returns a canned string — the test proves the *assembly*
(trace → dict shape) without spending an API call or needing a key.

### 3c. CLI entry — `recall explain <id>`

This is the "test by hitting an id" path. Add an `explain` subcommand to
`src/cli.py` that:
1. opens the DB (default `data/derek_handoff/derek_sample.db`, `--db` to override),
2. builds `LLMWhyExplainer()` (reads `OPENROUTER_API_KEY` from env — Doppler
   injects it),
3. calls `explain_principle`, prints the trace summary + the `why` paragraph.

Add a `--json` flag to dump the raw dict (handy for the frontend later).

---

## 4. How you run / test it

```bash
# 1. Offline trace tests — no key, no network, instant. Build this FIRST.
.venv/bin/python -m pytest tests/storage/test_trace.py -q

# 2. Agent assembly test — fake LLM, still no network.
.venv/bin/python -m pytest tests/pipeline/test_explain.py -q

# 3. The real thing — Doppler injects OPENROUTER_API_KEY, you "hit an id":
doppler run --project berkeley-hackathon --config dev -- \
  env PYTHONPATH=src .venv/bin/python -m cli explain <principle_id>

# grab a real id to test with:
sqlite3 data/derek_handoff/derek_sample.db "SELECT id, substr(text,1,50) FROM principles;"
# e.g. the 'hub' principle starts 92c6dd7f4731...
```

Cost note (CLAUDE.md §6): one `explain` call = one cheap LLM call. The trace
layer is free. So iterate on layer 1 freely; only spend tokens once the trace
shape looks right.

---

## 5. Build order (so you always have something working)

1. **`trace.py` + its test, against `derek_sample.db`.** Pure SQL → dataclasses.
   When `test_trace.py` is green you've proven the entire trace-back with no LLM,
   no key. This is 70% of the task and the part you fully control.
2. **`explain.py` with a `FakeExplainer` + its test.** Proves the prompt
   assembly and the output dict shape. Still offline.
3. **`LLMWhyExplainer`** — the ~15 lines that actually call OpenRouter (copy
   `link.py`). Now the agent is live.
4. **`recall explain` CLI** — wire it together, run it through Doppler against a
   real id. This is the demo.
5. **(phase 2)** `trace_edge` + the FastAPI `/principles/{id}/why` endpoint for
   the web UI.

---

## 6. Invariants / gotchas

- **Read-only.** This path never writes a principle and never fabricates
  provenance (CLAUDE.md §2 / §8). It only renders the chain that exists.
- **Cite, don't invent.** The agent must ground every claim in a supplied event.
  Thin evidence → say "this is a tentative read," don't bluff.
- **Pass the connection in.** Functions take a `sqlite3.Connection` arg rather
  than opening their own — that's what lets tests use a fixture DB and what keeps
  the HTTP layer (which reuses one connection per request) clean.
- **The schema is the contract.** Aaryan's `SCHEMA.md` is the source of truth for
  column names. If a column differs on disk, trust the disk and flag the drift.

---

## 7. Open decisions (flag before/while building, don't silently pick)

- **Default DB path** — `derek_sample.db` (safe, small) vs `recall.db` (real,
  big). Proposal: default to the sample, `--db` to switch.
- **Edge explanations** — do we also explain *why two principles connect*
  (the `trace_edge` + edge prompt)? Proposal: phase 2, after principles work.
- **HTTP endpoint now or later** — CLI is enough to demo and test. Proposal:
  ship CLI first; add the FastAPI route once the shape is settled.
</content>
</invoke>
