# Known bugs

Both bugs below were the same class: one malformed source row taking down a whole
ingest run. Both are now **fixed** with regression tests.

## Bug 1 — truncated `attributedBody` crashed iMessage ingest ✅ FIXED
`src/adapters/imessage.py` · `decode_attributed_body`

The decoder read a length prefix (`0x81` → 2 bytes, `0x82` → 4 bytes) with
`struct.unpack_from`, but only guarded that the first byte existed — not the bytes
the prefix promised. A BLOB ending right after the prefix raised an uncaught
`struct.error` that propagated through `read_records` → `ingest` and killed the run,
even though the docstring promises such rows return `None` (skipped).

- Trigger: a message whose `attributedBody` has the NSString anchor + `0x81`/`0x82`
  but too few trailing bytes (e.g. `decode_attributed_body(b'\x84\x01+\x81\x05')`).
- Fix: bounds-check that the prefix bytes exist (`pos + 3` / `pos + 5 <= len(blob)`)
  before unpacking; return `None` otherwise.
- Test: `tests/adapters/test_imessage_chatdb.py::test_attributed_body_truncated_length_prefix`.

## Bug 2 — NULL `ZDATECREATED` crashed photo ingest ✅ FIXED
`src/adapters/photos.py` · `_row_to_record` / `ingest_photos`

`apple_date_to_utc(row["date_created"])` was called with no `None` guard.
`ZDATECREATED` is nullable in `Photos.sqlite`, and real libraries have assets with
no capture time, so `None + 978_307_200` raised a `TypeError` that aborted the whole
`ingest_photos` run.

- Trigger: any photo/video asset with NULL `ZDATECREATED`.
- Fix: `_row_to_record` returns `None` for a NULL capture time, and `ingest_photos`
  filters those out — consistent with how the adapter already skips unusable rows.
- Test: `tests/adapters/test_photos.py::test_ingest_skips_null_date_created`.
