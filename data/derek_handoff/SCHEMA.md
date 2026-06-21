# Schema & Provenance Reference — Derek handoff

This documents every database in the Recall stack and **how they join so any
principle traces all the way back to ground-truth raw rows**. Provenance is the
*path*, not a stamped field: a principle is traceable because it was
consolidated from memories extracted from raw events, and each step leaves a
join.

Two stores matter:

1. **`recall.db`** (SQLite) — the materialised provenance graph. This is what
   you build the UI against. It has the raw `events`, the user-facing
   `principles` + `edges`, the synthesised `memories`, and the join tables that
   wire them together.
2. **pg0 / `hindsight`** (embedded Postgres) — Hindsight's internal memory
   engine. This is *where the memories come from*. You generally don't query it
   at runtime; `recall.db` is the flattened export of it. Documented here so you
   know what each `memories` row corresponds to upstream.

The sample DB `derek_sample.db` ships beside this doc: a 5-principle vertical
slice with the **complete** downward trace (every memory, every raw event), zero
dangling ids. Same schema as `recall.db` — point your code at it.

---

## 1. `recall.db` (SQLite) — the tables you query

### 1a. Raw layer — `events`

One source-agnostic row per message / item. Non-conversational sources (photos,
spotify) leave conversational fields null and carry payload in
`additional_data`.

| column | type | meaning |
|---|---|---|
| `id` | TEXT (PK) | event id (16-hex). Referenced by `memory_events.event_id`. |
| `t_utc` | TEXT | ISO-8601 UTC timestamp. |
| `author_role` | TEXT | `self` (the user) / `other` / etc. |
| `content` | TEXT | the message / item text. |
| `thread_id` | TEXT | conversation/thread grouping. |
| `reply_to` | TEXT | parent event in the thread, if any. |
| `raw_ref` | TEXT | pointer into the original source (e.g. `claude:<conv>#<msg>`). Ground truth. |
| `source` | TEXT | `imessage` / `claude` / `spotify` / `photo`. (Slice is all `claude`.) |
| `content_sha` | TEXT | sha256 of content, for dedupe. |
| `additional_data` | TEXT | JSON; per-source extra payload (`{}` for plain messages). |

### 1b. Capsules — `capsules`, `media`

Time-capsule write path. **Empty in the current export** (0 rows) but the schema
is present in both `recall.db` and the sample DB.

`capsules`: `id` (PK), `created_at`, `place_name`, `lat`, `lng`.
`media`: `id` (PK), `capsule_id` -> `capsules.id`, `kind`, `file_path`, `mime`,
`byte_size`, `exif_t`, `exif_lat`, `exif_lng`.

### 1c. Principle layer — `principles`, `edges`

The **user-facing** layer. Principles are the one-line mental models; edges are
the synthesised connections between them.

`principles`

| column | type | meaning |
|---|---|---|
| `id` | TEXT (PK) | principle id (64-hex). |
| `text` | TEXT | the one-line principle ("You make deliberate, informed decisions about your academic and research path."). |
| `confidence` | REAL | 0..1. |

`edges`

| column | type | meaning |
|---|---|---|
| `id` | TEXT (PK) | edge id. |
| `src_principle_id` | TEXT | -> `principles.id`. |
| `dst_principle_id` | TEXT | -> `principles.id`. |
| `relation` | TEXT | `supports` / `refines` / `contradicts`. |

### 1d. Memory layer — `memories`

The synthesised middle layer (one row per Hindsight memory_unit). Sits between
principles and raw events. Each memory is an abstraction Hindsight extracted from
a *document* (a windowed bundle of raw events).

| column | type | meaning |
|---|---|---|
| `memory_id` | TEXT (PK) | UUID. Equals `memory_units.id` in pg0. |
| `text` | TEXT | the abstracted memory ("The user analyzed a vaccine decision-making model..."). |
| `document_id` | TEXT | -> pg0 `documents.id` / `memory_units.document_id`; the source bundle this was extracted from. |
| `source` | TEXT | originating source (`claude`, ...). |
| `fact_type` | TEXT | Hindsight network: `experience` / `semantic` / `entity` / ... |
| `entities` | TEXT | comma-joined entity names. |
| `occurred_start` | TEXT | ISO timestamp the memory is anchored to. |
| `tags` | TEXT | JSON array, e.g. `["author:self","claude","network:experience"]`. |

### 1e. Join tables (the provenance wiring)

| table | columns | direction |
|---|---|---|
| `principle_memories` | `principle_id` -> principles, `memory_id` -> memories | principle ⟶ memories it was consolidated from |
| `edge_memories` | `edge_id` -> edges, `memory_id` -> memories | edge ⟶ memories that justify the connection |
| `memory_events` | `memory_id` -> memories, `event_id` -> events | memory ⟶ raw events it was extracted from |

---

## 2. The trace ladder (explicit SQL)

```
principle ──principle_memories──▶ memories ──memory_events──▶ events (raw ground truth)
edge      ──edge_memories──────▶ memories ──memory_events──▶ events
```

### 2a. Principle → all raw events

```sql
SELECT p.id   AS principle_id,
       p.text AS principle,
       m.memory_id,
       m.text AS memory,
       e.id   AS event_id,
       e.t_utc,
       e.author_role,
       e.content,
       e.raw_ref          -- pointer into the original source
FROM principles p
JOIN principle_memories pm ON pm.principle_id = p.id
JOIN memories m            ON m.memory_id     = pm.memory_id
JOIN memory_events me      ON me.memory_id    = m.memory_id
JOIN events e              ON e.id            = me.event_id
WHERE p.id = :principle_id
ORDER BY e.t_utc;
```

Walk it in stages for a click-through UI:

```sql
-- principle -> memories
SELECT m.* FROM memories m
JOIN principle_memories pm ON pm.memory_id = m.memory_id
WHERE pm.principle_id = :principle_id;

-- memory -> raw events
SELECT e.* FROM events e
JOIN memory_events me ON me.event_id = e.id
WHERE me.memory_id = :memory_id
ORDER BY e.t_utc;
```

### 2b. Edge → all raw events (why two principles connect)

```sql
SELECT ed.id AS edge_id, ed.relation,
       ed.src_principle_id, ed.dst_principle_id,
       m.memory_id, m.text AS memory,
       e.id AS event_id, e.content, e.raw_ref
FROM edges ed
JOIN edge_memories em ON em.edge_id   = ed.id
JOIN memories m       ON m.memory_id  = em.memory_id
JOIN memory_events me ON me.memory_id = m.memory_id
JOIN events e         ON e.id        = me.event_id
WHERE ed.id = :edge_id
ORDER BY e.t_utc;
```

### 2c. Count trace depth (sanity)

```sql
SELECT p.id, substr(p.text,1,50) AS principle,
       COUNT(DISTINCT pm.memory_id) AS n_memories,
       COUNT(DISTINCT me.event_id)  AS n_raw_events
FROM principles p
LEFT JOIN principle_memories pm ON pm.principle_id = p.id
LEFT JOIN memory_events me        ON me.memory_id   = pm.memory_id
GROUP BY p.id
ORDER BY n_raw_events DESC;
```

---

## 3. pg0 / Hindsight (embedded Postgres) — where memories come from

This is Hindsight's engine. `recall.db.memories` is a flattened export of its
`memory_units`; `recall.db.memories.document_id` points straight at it. You
rarely need to touch pg0 directly, but here's the linkage so the provenance is
honest end-to-end.

**Connection** (embedded, started on demand via `src/runtime/hindsight.py`):

| param | value |
|---|---|
| host / port | `127.0.0.1` : `5432` |
| database | `hindsight` (the app aliases it as `pg0` via `HINDSIGHT_API_DATABASE_URL`) |
| user / password | `hindsight` / `hindsight` |
| data dir | `~/.pg0/instances/hindsight/data` (config in `instance.json`) |

Start it (local read, no OpenRouter/Doppler needed):

```bash
PGBIN=~/.pg0/installation/18.1.0/bin
"$PGBIN/pg_ctl" -D ~/.pg0/instances/hindsight/data -o "-p 5432" -w start
PGPASSWORD=hindsight "$PGBIN/psql" -h 127.0.0.1 -p 5432 -U hindsight -d hindsight
```

### Tables (public schema), counts at export time

| table | rows | relevance |
|---|---|---|
| `memory_units` | 407 | **the memories.** `id` == `recall.db.memories.memory_id`. |
| `documents` | 13 | **the raw source bundle.** `original_text` holds the windowed episode text the memory was extracted from. |
| `chunks` | 108 | document split into chunks for embedding. |
| `memory_links` | 7373 | graph edges between memory_units (entity co-mention etc.). |
| `entities` | 396 | extracted entities. |
| `unit_entities` | 1280 | memory_unit ↔ entity join. |
| `entity_cooccurrences` | 927 | entity co-mention stats. |
| `banks` | 1 | the memory bank (default `imessage-v0`). |
| `chunks`/`llm_requests`/`async_operations`/`audit_log`/… | — | engine internals; not needed for provenance. |

### `memory_units` (the columns that matter for provenance)

| column | type | meaning |
|---|---|---|
| `id` | uuid | == `recall.db.memories.memory_id`. |
| `bank_id` | text | which memory bank. |
| `document_id` | text | -> `documents.id`; the source bundle. == `recall.db.memories.document_id`. |
| `text` | text | the memory abstraction (== `memories.text`). |
| `fact_type` | text | network (`experience`/`semantic`/…) (== `memories.fact_type`). |
| `embedding` | vector | qwen embedding (pgvector). Not exported to recall.db. |
| `occurred_start` / `occurred_end` / `event_date` | timestamptz | temporal anchoring. |
| `tags` | text[] | == `memories.tags`. |
| `source_memory_ids` | uuid[] | consolidation lineage (memories merged into this one). |
| `metadata` | jsonb | misc. |

### `documents`

| column | type | meaning |
|---|---|---|
| `id` | text | == `memory_units.document_id` and `recall.db.memories.document_id`. |
| `original_text` | text | the raw windowed episode text — the human-readable ground truth behind the memory. |
| `content_hash` | text | dedupe. |
| `retain_params` | jsonb | how it was ingested. |

### How pg0 relates to `recall.db.events` (the materialisation)

Hindsight's `documents.original_text` is the *windowed episode* — a bundle of raw
events concatenated. The mapping **back to individual `events.id`** was
materialised during export (the `memory_events` table), derived from the
per-memory `raw_events` list (see `data/bank_snapshot.json`, the 407-row dump of
memory_units with their `raw_events` inline). So:

```
pg0 memory_units.id ─┐
                     ├─▶ recall.db.memories.memory_id
pg0 documents.id ────┴──▶ recall.db.memories.document_id (raw bundle text)
                          recall.db.memory_events ──▶ recall.db.events.id (per-event grain)
```

Net: **you do not need pg0 at runtime.** `recall.db` already carries the full
ladder from principle to individual raw event. pg0 is documented so the link to
the synthesised memory + its full source bundle text (`documents.original_text`)
is available if the UI wants to show the raw episode, not just the per-event rows.

---

## 4. `derek_sample.db` — the vertical slice

Built by `build_sample.py`, verified by `verify_sample.py` (both in this dir).
Same schema as `recall.db`. Contents:

| table | rows |
|---|---|
| events | 24 |
| principles | 5 |
| edges | 3 (all internal to the 5 principles) |
| memories | 9 |
| principle_memories | 11 |
| edge_memories | 10 |
| memory_events | 138 |
| capsules / media | 0 (empty in source) |

**The 5 principles** (chosen as a connected edge cluster, each with a deep raw
trace so both principle→raw and edge→raw walks are exercisable):

| id (prefix) | conf | raw events | text |
|---|---|---|---|
| `92c6dd7f4731` | 0.7 | 22 | You make deliberate, informed decisions about your academic and research path. (**hub** — in all 3 edges) |
| `a9476af4e29c` | 0.5 | 22 | You align your research choices with a clear, long-term normative goal. |
| `b57296638217` | 0.5 | 22 | You value building a strong academic and professional foundation. |
| `ed864bf62740` | 0.5 | 22 | You prioritize research directions focused on AI safety. |
| `b15f78146dc7` | 0.75 | 2 | You apply rigorous mathematical and decision-theoretic reasoning. |

**The 3 edges:**

- `a9476af4` **refines** `92c6dd7f` (22 raw)
- `92c6dd7f` **supports** `b5729663` (22 raw)
- `b15f7814` **supports** `92c6dd7f` (2 raw)

**Guarantee:** every principle and edge in the slice traces to ≥1 raw event, and
every id in every join table resolves to a real row — no orphan `memory_id`s, no
orphan `event_id`s. Re-verify any time:

```bash
PYTHONPATH=src .venv/bin/python data/derek_handoff/verify_sample.py
# -> PASS: zero dangling ids; every principle and edge traces to raw events.
```
