"""EDA over the retained memory bank snapshot (data/bank_snapshot.json).

Surfaces issues + opportunities before principle-minting (rung ③/④) is built on
top of these memories. Computes:

1. Distribution (per-source counts, raw_event fan-out, fact_type, entities).
2. The spotify-skew question (per-source richness).
3. Clustering preview (entity-shared + temporal-proximity; singletons + cross-source).
4. Provenance sanity (all trace to raw_events; flag possible hallucinations).
5. Surprises worth knowing before minting.

Run: PYTHONPATH=src .venv/bin/python scripts/eda_bank.py
No network; reads only the local snapshot.
"""

from __future__ import annotations

import collections
import itertools
import json
import re
from datetime import datetime
from pathlib import Path

SNAPSHOT = Path("data/bank_snapshot.json")

# Entities that carry no clustering signal: present on most memories ("user") or
# templating artifacts. Coordinates (photos) are filtered separately by regex.
GENERIC_ENTITIES = {"user", "photo", "speaker", "assistant", "narrator", "friend"}
COORD_RE = re.compile(r"^[-0-9.\s]+$")
# Date / template vocabulary the renderer emits that is not in raw content; used
# to avoid flagging templated photo/spotify facts as hallucinations.
TEMPLATE_WORDS = {
    "user",
    "took",
    "photo",
    "photos",
    "song",
    "album",
    "when",
    "listened",
    "involving",
    "friend",
    "sequence",
    "series",
    "including",
    "speaker",
    "assistant",
    "narrator",
    "currently",
    "recently",
    "from",
    "this",
    "that",
    "with",
    "their",
    "they",
    "have",
    "been",
    "undertaking",
    "close",
    "rapid",
    "succession",
    "coordinates",
    "location",
    "unknown",
    "prior",
    "edit",
    "feat",
    "approximately",
    "between",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "three",
    "four",
    "five",
    "two",
    "one",
}


def load() -> list[dict]:
    return json.loads(SNAPSHOT.read_text())


def split_entities(memory: dict) -> list[str]:
    raw = memory.get("entities") or ""
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def specific_entities(memory: dict) -> set[str]:
    """Entities that can plausibly link two memories into the same moment."""
    out = set()
    for e in split_entities(memory):
        if e in GENERIC_ENTITIES or COORD_RE.match(e):
            continue
        out.add(e)
    return out


def parse_ts(memory: dict) -> datetime | None:
    t = memory.get("occurred_start")
    return datetime.fromisoformat(t) if t else None


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def report_distribution(memories: list[dict]) -> None:
    hr("1. DISTRIBUTION")
    by_source = collections.Counter(m["source"] for m in memories)
    print(f"total memories: {len(memories)}")
    print(f"by source:      {dict(by_source)}")

    fan = collections.Counter(len(m["raw_events"]) for m in memories)
    fan_vals = [len(m["raw_events"]) for m in memories]
    print(
        f"\nraw_event fan-out (1:N): "
        f"min={min(fan_vals)} max={max(fan_vals)} "
        f"mean={sum(fan_vals) / len(fan_vals):.1f}"
    )
    print(f"  distribution (n_events -> n_memories): {dict(sorted(fan.items()))}")
    singleton_evt = sum(1 for v in fan_vals if v == 1)
    print(f"  memories backed by a single raw event: {singleton_evt}")

    print(f"\nfact_type: {dict(collections.Counter(m['fact_type'] for m in memories))}")

    ent_freq = collections.Counter()
    for m in memories:
        for e in split_entities(m):
            ent_freq[e] += 1
    print("\ntop entities across memories:")
    for e, c in ent_freq.most_common(15):
        print(f"  {c:3d}  {e}")
    print(f"distinct entities total: {len(ent_freq)}")


def report_spotify_skew(memories: list[dict]) -> None:
    hr("2. SPOTIFY-SKEW: is spotify shallow vs imessage/photos?")
    print(f"{'source':10} {'n':>3} {'avg_text':>9} {'avg_ent':>8} {'avg_spec_ent':>12} fact_types")
    for s in ("imessage", "spotify", "photos"):
        ms = [m for m in memories if m["source"] == s]
        if not ms:
            continue
        tl = [len(m["text"]) for m in ms]
        ent = [len(split_entities(m)) for m in ms]
        spec = [len(specific_entities(m)) for m in ms]
        ft = dict(collections.Counter(m["fact_type"] for m in ms))
        print(
            f"{s:10} {len(ms):>3} {sum(tl) / len(tl):>9.1f} "
            f"{sum(ent) / len(ent):>8.2f} {sum(spec) / len(spec):>12.2f} {ft}"
        )
    print(
        "\nNote: spotify avg_text is inflated by bundled song *sequences*, and its\n"
        "high entity count is artist/track names (rarely reusable across sources).\n"
        "fact_type diversity: only imessage produces 'world' facts; spotify+photos\n"
        "are 100% 'experience' (a single shallow predicate: listened / took photo)."
    )


def _cluster_by_entity(memories: list[dict]) -> list[list[int]]:
    """Union-find over shared *specific* entities (no temporal chaining)."""
    n = len(memories)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    ent_to_mem: dict[str, list[int]] = collections.defaultdict(list)
    for i, m in enumerate(memories):
        for e in specific_entities(m):
            ent_to_mem[e].append(i)
    for members in ent_to_mem.values():
        for j in range(1, len(members)):
            union(members[0], members[j])

    clusters: dict[int, list[int]] = collections.defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)
    return list(clusters.values())


def report_clustering(memories: list[dict]) -> None:
    hr("3. CLUSTERING PREVIEW (entity-shared, no temporal chaining)")
    clusters = _cluster_by_entity(memories)
    sizes = sorted((len(c) for c in clusters), reverse=True)
    singletons = sum(1 for s in sizes if s == 1)
    print(f"clusters: {len(clusters)}   sizes: {sizes[:12]}")
    print(
        f"SINGLETONS: {singletons} / {len(memories)} "
        f"({100 * singletons / len(memories):.0f}%) -- dropped (principles need >=2)"
    )
    print(f"clusters with >=2 (mintable): {sum(1 for s in sizes if s >= 2)}")

    print("\nmintable clusters (>=2):")
    cross = 0
    for c in sorted(clusters, key=len, reverse=True):
        if len(c) < 2:
            continue
        srcs = collections.Counter(memories[i]["source"] for i in c)
        is_cross = len(srcs) > 1
        cross += is_cross
        bridge = set.intersection(*(specific_entities(memories[i]) for i in c))
        print(f"  n={len(c)} srcs={dict(srcs)} cross={is_cross} bridge_entities={sorted(bridge)}")
        for i in c[:3]:
            print(f"      {memories[i]['source']:8} | {memories[i]['text'][:68]}")
    print(f"\nentity-based cross-source clusters: {cross}")
    print(
        "  -> photos carry NO non-coordinate entities, so they can never join an\n"
        "     entity cluster. Any spotify<->imessage bridge is a coincidental shared\n"
        "     app/word (e.g. 'notion'), not a real shared moment."
    )

    _report_temporal_cooccurrence(memories)


def _report_temporal_cooccurrence(memories: list[dict], window_s: int = 3600) -> None:
    print(f"\n-- temporal co-occurrence (pairwise, <= {window_s // 60} min) --")
    for s in ("imessage", "spotify", "photos"):
        ms = [m for m in memories if m["source"] == s]
        have = sum(1 for m in ms if m["occurred_start"])
        print(f"  {s:9} with occurred_start: {have}/{len(ms)}")
    stamped: list[tuple[int, datetime]] = []
    for i, m in enumerate(memories):
        t = parse_ts(m)
        if t is not None:
            stamped.append((i, t))
    pairs: collections.Counter = collections.Counter()
    for (i, ti), (j, tj) in itertools.combinations(stamped, 2):
        if abs((ti - tj).total_seconds()) <= window_s:
            a, b = sorted((memories[i]["source"], memories[j]["source"]))
            pairs[(a, b)] += 1
    cross_pairs = {k: v for k, v in pairs.items() if k[0] != k[1]}
    print(f"  cross-source temporal pairs: {cross_pairs}")
    print(
        "  -> temporal proximity is the ONLY bridge that reaches photos & spotify.\n"
        "     real moments (photo + the song playing + the text about it) are\n"
        "     recoverable by time, not by entity."
    )


def report_provenance(memories: list[dict]) -> None:
    hr("4. PROVENANCE SANITY")
    empty = [m for m in memories if not m["raw_events"]]
    print(f"memories with empty raw_events (broken chain): {len(empty)}")
    print(f"all {len(memories)} trace to >=1 raw event: {len(empty) == 0}")

    scored = []
    for m in memories:
        text_w = words(m["text"]) - TEMPLATE_WORDS
        raw_w: set[str] = set()
        for r in m["raw_events"]:
            raw_w |= words(r.get("content") or "")
            for v in (r.get("additional_data") or {}).values():
                raw_w |= words(str(v))
        novel = text_w - raw_w
        if text_w:
            scored.append((len(novel) / len(text_w), sorted(novel)[:8], m))

    print("\nhighest unsupported-token ratio (potential extraction drift):")
    for ratio, novel, m in sorted(scored, key=lambda x: x[0], reverse=True)[:6]:
        print(f"  ratio={ratio:.2f} src={m['source']:8} novel={novel}")
        print(f"      text: {m['text'][:80]}")
    print(
        "\n  Note: high ratios concentrate on photos (date/template vocabulary the\n"
        "  renderer adds), not factual claims -- not hallucination."
    )


def report_surprises(memories: list[dict]) -> None:
    hr("5. SURPRISES WORTH KNOWING BEFORE MINTING")
    no_ts = collections.Counter(m["source"] for m in memories if not m["occurred_start"])
    print(f"memories missing occurred_start by source: {dict(no_ts)}")
    print("  -> ~half of imessage memories ('world' facts) have no timestamp, so")
    print("     they are invisible to any time-window join.")
    world = [m for m in memories if m["fact_type"] == "world"]
    print(f"\n'world' facts (standing facts, not behavior): {len(world)}")
    print("  -> these describe relationships/attributes, not repeated behavior;")
    print("     behavioral-corroboration gating should not count them as evidence.")


def main() -> None:
    memories = load()
    report_distribution(memories)
    report_spotify_skew(memories)
    report_clustering(memories)
    report_provenance(memories)
    report_surprises(memories)
    print()


if __name__ == "__main__":
    main()
