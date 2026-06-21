# API Contract — Capsule Write-Path

The endpoints a frontend uses to create and read **capsules** (user-created
memories: a place + media). This is the *active* raw_data path; it persists to
SQLite and saves media to disk. It does **not** yet run abstraction / Hindsight
`retain` / the swarm — that is a downstream stage (see
[`TIME_CAPSULE_FLYWHEEL.md`](../design/TIME_CAPSULE_FLYWHEEL.md)).

Base URL in dev: `http://localhost:8000`. CORS allows `GET` and `POST` from
`http://localhost:5173`.

> **Naming:** this `Capsule` (captured memory) is intentionally distinct from the
> swarm-facing `TimeCapsule` (raw_data refs + intent) in the flywheel doc.

---

## Objects

### Capsule
| Field | Type | Notes |
|---|---|---|
| `id` | string | server-assigned, stable |
| `created_at` | string (ISO-8601 UTC) | server-set seal time |
| `place_name` | string | required |
| `lat` | number \| null | optional |
| `lng` | number \| null | optional |
| `media` | Media[] | may be empty |

### Media
| Field | Type | Notes |
|---|---|---|
| `id` | string | server-assigned |
| `capsule_id` | string | owning capsule |
| `kind` | `"photo" \| "audio" \| "video" \| "text"` | inferred from MIME |
| `file_path` | string | path relative to the media root (server-side) |
| `mime` | string | e.g. `image/jpeg` |
| `byte_size` | number | bytes |
| `exif_t` | string \| null | reserved (not parsed yet) |
| `exif_lat` | number \| null | reserved |
| `exif_lng` | number \| null | reserved |

---

## Endpoints

### `POST /api/capsules`  → `201`
Create a capsule. **`multipart/form-data`** (so real files upload, not base64).

Form fields:
- `place_name` (required, non-empty)
- `lat` (optional, float)
- `lng` (optional, float)
- `media` (zero or more files; repeat the field for multiple)

Returns the created **Capsule**.

Errors:
- `422` — `place_name` missing/blank.
- `415` — an uploaded file's type maps to no supported `kind`.

```js
const form = new FormData();
form.append("place_name", "Moffitt Library");
form.append("lat", "37.872");
form.append("lng", "-122.260");
form.append("media", fileInput.files[0]);   // append again for more files
const capsule = await fetch("http://localhost:8000/api/capsules", {
  method: "POST",
  body: form,                                 // do NOT set Content-Type manually
}).then(r => r.json());
```

### `GET /api/capsules` → `200`
```json
{ "capsules": [ { /* Capsule */ } ] }   // newest first
```

### `GET /api/capsules/{id}` → `200` | `404`
Returns one **Capsule**, or `404` if unknown.

---

---

## Passive raw_data + traceability (not an HTTP endpoint)

The same SQLite store also persists **passive** sources (iMessage today) in an
`events` table, so both paths share one durable home. iMessage is wired through
the CLI:

```bash
# ingest chat.db -> events.jsonl AND persist to the durable store
recall ingest --top-n 5            # add --no-store to skip persistence
```

Each stored event keeps:
- `content` — the message text as ingested (your durable evidence copy);
- `raw_ref` — `chat.db#<ROWID>`, a pointer back to the original message;
- `content_sha` — a SHA-256 of the content at ingest time.

**Traceability guarantee.** A finding can be traced to its source message, and
`CapsuleStore.verify_event(id)` proves the stored copy is byte-identical to what
was ingested (`True` / `False` / `None` if unknown) — independent of whether
`chat.db` is later vacuumed or unavailable. `raw_ref` is the "jump to original"
link; the stored `content` + `content_sha` is the self-contained proof.

---

## Not in scope here (downstream)
- capsule → canonical `Event` conversion + Hindsight `retain`
- principle alignment / the agentic swarm / priority queues
- serving the media binaries back over HTTP (only metadata is returned today)
- Spotify / LLM-export ingestion connectors (no parser yet; storage is ready —
  any source that emits `Event`s can call `store.add_events(...)`)
