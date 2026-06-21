# LLM-chat & Photo raw_data Adapters — Design

Date: 2026-06-20
Author: Aaryan (with Claude Code)
Status: draft for review (Photos.sqlite EDA complete; folded into §4)

## 1. Scope & architectural placement

This work implements the **bottom rung of the synthesis ladder** in
[`design/TIME_CAPSULE_FLYWHEEL.md`](../../../design/TIME_CAPSULE_FLYWHEEL.md) §2:
turn two disparate raw sources into canonical `raw_data` rows that preserve exact
`source_refs`, so provenance never snaps. We do **not** touch memory networks,
consolidation, principles, or the swarm — only ingest.

Two adapters:

1. **LLM chats** — parse an already-unzipped Claude data export into canonical
   conversational rows.
2. **Photos** — read-only ingest of Apple Photos metadata from the local
   `Photos.sqlite`.

Both land in the existing durable SQLite store (`src/recall/store.py`,
`CapsuleStore`) beside the iMessage `events` table, reusing its
per-call-connection pattern and `content_sha` provenance hash.

A teammate owns iMessage and Spotify; this spec deliberately does not modify their
code. We reuse the *shape* of `recall.schema.Event` but add sibling tables rather
than overloading `events`.

## 2. Model strategy

- **Pydantic** (`BaseModel`) for all new **parse-time** models — strict validation
  over messy export JSON and DB rows. (`src/models/`.)
- The existing `Event` / `Episode` / `Capsule` frozen dataclasses are **left
  unchanged** — the flywheel doc §11 explicitly reuses them.
- A shared Pydantic base, `ChatEvent`, captures the conversational-message shape
  common to iMessage and LLM chats. The LLM canonical row is a **sibling** of the
  iMessage `Event`: it inherits the base fields but gets its **own table**, so the
  two sources stay structurally aligned without one overwriting the other.

`ChatEvent` base fields (mirrors `Event`):
`id, t_utc, author_role, content, thread_id, reply_to, raw_ref, source`.

## 3. Component 1 — LLM-chat adapter (`src/adaptors/llm_chats.py`)

### Input
An already-unzipped Claude export directory. We own all post-unzip handling.
Reference data lives at
`/Users/aaryanrampal/personal/hindsight-setup/ai_chats/claude/data/claude/`:
- `conversations.json` — list of conversations (1,633 convos, 20,130 messages in
  the reference export; 21 empty conversations).
- `projects/*.json`, `users.json`, `memories.json` — out of scope for v0 (we
  ingest conversations only; the rest are noted for later).

### Export shape (verified against the real file)
- Conversation: `{uuid, name, summary, created_at, updated_at, account, chat_messages}`.
- Message: `{uuid, sender, text, content, created_at, updated_at, attachments,
  files, parent_message_uuid}`.
  - `sender ∈ {human, assistant}`.
  - `content` is a list of typed blocks; observed types:
    `text, thinking, tool_use, tool_result, voice_note, token_budget, flag`.
  - `parent_message_uuid` gives real reply chains (20,128/20,130 messages have a
    parent) — usable directly as `reply_to`.

### Parse-time Pydantic models (`src/models/llm_export.py`)
- `ClaudeExport` (wraps the directory / loaded conversation list)
- `ClaudeConversation` (`uuid, name, created_at, updated_at, chat_messages`)
- `ClaudeMessage` (`uuid, sender, text, content, created_at, parent_message_uuid`)
- `ClaudeContentBlock` (`type, text?, name?` — enough to render text + note tools)

These are faithful to the export; validation is strict (unknown senders fail loud).

### Canonical mapping → `ChatEvent` (source = `"claude"`)
- `author_role`: `human → "self"`, `assistant → "other"` (both turns stored,
  role-tagged — same convention as iMessage; `self` is the first-person signal).
- `content`: concatenated `text` blocks (and `text` of any block that carries it).
  **Privacy rule (carried from the `memories` project's AGENTS.md):**
  - `thinking` blocks are **dropped**.
  - `tool_use` / `tool_result` blocks record only a marker that a tool ran
    (e.g. `[tool: <name>]`) — never raw arguments, command output, or result text.
- `thread_id` = conversation `uuid`.
- `reply_to` = `parent_message_uuid` (or `None` for the 2 roots).
- `raw_ref` = `claude:<conversation_uuid>#<message_uuid>` (exact source ref —
  this is the provenance link that must survive).
- `t_utc` = parsed `created_at` (ISO-8601, already UTC `Z`).
- `id` = stable hash of `(thread_id, message_uuid)` — deterministic, idempotent.

Messages whose rendered content is empty (after dropping thinking/tool blocks,
e.g. a pure `voice_note` with no transcript) are skipped, mirroring the iMessage
ingest's "skip undecodable rows" behavior.

### Storage
A new module `src/recall/llm_store.py` owns the `llm_messages` table, columns
mirroring `ChatEvent` plus `content_sha` (provenance hash). It reuses the
*idiom* of `recall.store` (per-call connection, `PRAGMA foreign_keys`,
`content_sha`) but does **not** edit `store.py`, so it never collides with the
teammate's iMessage code or the parallel photo agent. `add_llm_messages(events)`
is idempotent on `id` (`INSERT OR REPLACE`), matching `add_events`.

## 4. Component 2 — Photo adapter (`src/adaptors/photos.py`)

The Apple Photos DB is queryable read-only at
`~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`. Read-only EDA
(see below) confirmed it opens cleanly in immutable mode despite active WAL:
`sqlite3.connect("file:<db>?mode=ro&immutable=1", uri=True)`. If a future lock
prevents this, fall back to copying the three sidecar files (`.sqlite`, `-wal`,
`-shm`) to a temp dir and opening the copy read-only — never write the originals.

### EDA findings (verified against the live DB, read-only)
8,695 assets (7,585 photos + 1,110 videos), date range 2009-01-22 → 2026-06-20.

| Table | Rows | Purpose |
|---|---|---|
| `ZASSET` | 8,695 | main asset row (date, GPS, dir/filename, dims, flags) |
| `ZADDITIONALASSETATTRIBUTES` | 8,695 | extended attrs incl. original filename |
| `ZDETECTEDFACE` | 8,271 | per-face detections, FK to asset + person |
| `ZPERSON` | 3,429 | people/face clusters (32 named, rest anonymous) |
| `ZSCENECLASSIFICATION` | 325,552 | scene ML enums + confidence (no built-in labels) |

Gotchas confirmed:
- **Apple Core Data epoch:** capture date needs `+978_307_200` to become a Unix
  timestamp (reuse the iMessage ingest's epoch handling pattern).
- **GPS sentinel:** missing GPS is stored as `(-180.0, -180.0)` — map to `None`.
- **Originals path:** `originals/<ZDIRECTORY>/<ZFILENAME>` relative to the library.
- **Scene labels:** scene IDs are internal Apple ML enums with **no** human-readable
  label table. v0 stores at most the top scene id + confidence; readable scene
  tags are deferred (would need a maintained enum→label mapping). Named **people**
  (32) are usable directly; anonymous face clusters are skipped for v0.

### Shape
- Read-only open, same pattern as `chat.db` ingest.
- `PhotoRecord` Pydantic model: `id, captured_at (Apple-epoch → UTC), lat, lng
  (sentinel → None), original_filename, original_path, width, height, is_favorite,
  is_hidden, is_trashed, kind (photo/video), people (named only)`.
- Stored in a dedicated `photos` table referencing originals on disk.
  **No binary copying this pass** — rows reference originals, keeping the DB small
  (same philosophy as `Media.file_path`).
- `raw_ref` = `photos.sqlite#<ZASSET.Z_PK>` (exact source ref).
- Exact column names are captured in the build task from the EDA agent's column
  reference (pending its compact reply); the adapter pins them rather than
  guessing.

## 5. Data flow

```
unzipped Claude export ──(Pydantic parse)──▶ ChatEvent ──▶ store.add_llm_messages()
Photos.sqlite (read-only) ──(Pydantic)─────▶ PhotoRecord ─▶ store.add_photos()
```

Downstream (out of scope here): `episodes.py` can window `llm_messages` into
episodes for free since conversations are already threaded; `load.py` can push
them to Hindsight. Both inherit the `source_refs` we preserve.

## 6. Error handling

- Fail fast on malformed export structure (Pydantic validation errors name the
  field and conversation).
- Skip individual undecodable/empty messages rather than aborting a run (log a
  count, mirroring the iMessage ingest).
- Photos DB: if the locked DB can't be opened immutable, copy the three sidecar
  files to a temp dir and open the copy read-only; never write the originals.

## 7. Testing

- LLM: Pydantic parsing against a small fixture sliced from the real export
  (a few conversations incl. one with tool blocks, one empty, one with a deep
  reply chain). Canonical mapping asserts role/ref/content-privacy rules.
  Round-trip through an in-memory `CapsuleStore`.
- Photos: tested against a copied throwaway DB; assert Apple-epoch conversion,
  GPS handling, and ref construction.
- Verification gate before "done": `ruff check`, `ruff format --check`,
  `ty check`, `pytest -q`.

## 8. Build orchestration

After approval, spawn parallel sub-agents per the `dispatching-parallel-agents`
skill:
- Agent A: LLM-chat adapter + models + table + tests (fully specified now).
- Agent B: photo adapter + model + table + tests (starts once the EDA report is
  folded into §4).

The two adapters share only the `ChatEvent` base and the store file; work is
otherwise independent.

## 9. Open questions / boundaries

- `projects/`, `users.json`, `memories.json` from the Claude export are deferred
  (v0 ingests conversations only).
- Other LLM sources (ChatGPT, Codex, etc.) are out of scope; the `source` field
  and `ChatEvent` base leave room to add them as sibling adapters later.
- Photo scenes are internal ML enums with no label table, so readable scene tags
  are deferred; v0 stores geo/time/file metadata + named people only.
- No embeddings / Hindsight load in this pass — strictly raw_data ingest.
