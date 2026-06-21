Bug 1 — src/adaptors/imessage.py:85, truncated attributedBody crashes iMessage ingest
The decoder for the message-body BLOB reads a length prefix (0x81 → 2 bytes, 0x82 → 4 bytes) with struct.unpack_from, but only guards that the first byte exists — not the bytes the prefix promises. A BLOB that ends right after the prefix raises an uncaught struct.error.

- Trigger: a message whose attributedBody has the NSString anchor + 0x81/0x82 but too few trailing bytes.
- Effect: struct.error propagates up through read_records → ingest with no try/except → the whole iMessage run dies. The docstring promises such rows return None (skipped). Reproduced: decode_attributed_body(b'\x84\x01+\x81\x05') → unpack_from requires a buffer of at least 6 bytes.
- Fix: bounds-check start + length <= len(blob) (and that the prefix bytes exist) before unpacking; return None if not.

Bug 2 — src/adaptors/photos.py:117, NULL ZDATECREATED crashes photo ingest
apple_date_to_utc(row["date_created"]) is called with no None-guard. ZDATECREATED is nullable in Photos.sqlite and real libraries have assets with no capture time.

- Trigger: any photo/video asset with NULL ZDATECREATED.
- Effect: None + 978_307_200 → TypeError, aborting ingest_photos entirely. Other columns in that function are defended with or fallbacks; the timestamp isn't. Reproduced: apple_date_to_utc(None) → TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'.
- Fix: skip the row (or fall back) when date_created is None, consistent with how the adapter already skips undecodable rows.

Both are the same class of bug: one malformed source row taking down the whole ingest. Low individual likelihood, but they'd bite on real-world data, which is exactly when you don't want a hard crash.
