# Redis vs Hindsight — backend structure & where each fits

Scope: classify the **backend memory structure** of Redis-based agent memory, compare
it head-to-head with Hindsight (which Recall already uses), and map both onto the
[Time Capsule Flywheel](TIME_CAPSULE_FLYWHEEL.md). The short version sits at the
top; sourced detail and the full comparison follow.

---

## TL;DR

- **Redis is a flat vector + metadata store. It is not a graph DB and not a
  cognitive/reflection layer.** RedisGraph is end-of-life (Jan 2025); there is no
  native replacement.
- **Hindsight is a cognitive layer on top of a vector store** (Postgres +
  pgvector): it does LLM extraction, entity resolution, and a REFLECT step that
  synthesizes new cross-memory beliefs/principles. That reflect step is the part
  no Redis product has.
- They are **complementary, not alternatives**. In the flywheel, **Hindsight is
  the vertical** (raw → episodic/semantic/graph → principles, with grounding links
  back down); **Redis is the horizontal plumbing** (the two work queues + a
  semantic cache) that makes the swarm spin fast and survive restarts.
- The one thing to fix in the flywheel doc: the §1 node labeled
  `"Hindsight / Redis"` conflates them. Split it — Hindsight is the store/synthesis
  spine; Redis backs the queues and an optional recall cache.

---

## 1. Where Redis and Hindsight fit the flywheel

### Hindsight = the synthesis ladder itself (flywheel §2 + principles)

Hindsight *is* the three-to-four rung ladder the flywheel draws, already built:

- **memory-networks rung** — episodic (Experiences), semantic (World facts),
  graphical (Entity summaries). These are exactly the boxes in the flywheel's §2
  `MEM` subgraph.
- **principles rung** — Hindsight's **Evolving beliefs / mental models** network.
  That is the `PRIN` node; §3 of the flywheel doc already defines
  `principle = Hindsight mental model`.
- The **REFLECT step** is the "consolidation" arrow (`MEM --> PRIN`) and much of
  what the **swarm's Arbiter** (flywheel §5) wants to do: synthesize non-obvious
  cross-memory connections with strict evidence/inference separation. That split
  is what powers the §2 dotted "drill down for provenance" arrows and lets the
  Critic re-read `raw_refs` instead of trusting a summary.

So Hindsight owns the **vertical** axis. Nothing in Redis does this — even the
Redis Agent Memory Server stops at flat typed records with no reflect step that
produces new beliefs. Swapping Hindsight for Redis would delete the top rung of
the ladder, which is the only rung the user reads. **Keep Hindsight as the spine
of flywheel §2 and §5.**

### Redis = the bearings (flywheel §4 queues + speed)

Redis fits the parts of the flywheel Hindsight doesn't cover. In priority order:

1. **The two queues (flywheel §4) — `time_capsule_queue` + `ui_queue`.** Cleanest
   fit; the doc practically asks for it ("the queues are the only coupling between
   subsystems… independently restartable… state inspectable"). Redis Streams (or
   sorted sets for the HIGH/NORMAL priority bands) give a durable, inspectable,
   restartable work queue with consumer groups so the swarm's Retriever/Critic/
   Arbiter agents (§5) pull without colliding. `TimeCapsule.priority="high"` maps
   to a sorted-set score or a second stream. Buys real swarm concurrency and
   restart-survival versus a file queue. Medium effort, high payoff.
2. **Semantic cache in front of the swarm's `recall` (flywheel §5 Retriever).** The
   Retriever calls Hindsight `recall(episodic, semantic, principles)` per capsule,
   and §8 flags "dedup of near-identical contradictions" as open. A RedisVL
   `SemanticCache` in front of recall returns cached retrieved-context for
   near-duplicate capsules and can short-circuit re-running the same contradiction
   detection — directly addressing that open question. Cuts latency + LLM cost on
   the hot path. Low effort, drop-in.
3. **Working-memory / session layer — only if the §1 UI confirmation loop is
   conversational.** When the user elaborates (`ASK → USER → elaboration`), RedisVL
   `SemanticMessageHistory` holds that conversation's short-term state before it's
   distilled into a high-priority `TimeCapsule` and handed to Hindsight as
   long-term. Skip unless the confirmation loop is a chat, not a form field.

### What Redis does NOT replace

- It does **not** store principles/mental models — no reflect/synthesis.
- Its `entities` field (Agent Memory Server) is flat metadata, **not** the
  graphical/relations rung. The §2 `GRAPH` box is Hindsight entity summaries. True
  traversable entity→relation→entity edges with temporal validity would be
  **Graphiti**, not Redis.

### Hackathon vs production

- **Hackathon:** keep the queues as the POC's file-based state (flywheel §4 cites
  that philosophy); Redis Streams is nice-to-have. The **semantic cache (#2) is the
  single highest-ROI Redis add** — small, visible latency/cost win on the swarm
  loop. Skip the chat session layer unless the demo is conversational.
- **Production:** promote the queues to Redis Streams (#1) for real swarm
  concurrency, backpressure (the §8 "user never answers ui_queue" open question),
  and restartability.

### One concrete edit to the flywheel doc

In the §1 mermaid, split the conflated node:

- keep `HS[("Hindsight<br/>episodic · semantic · people · principles")]` as the
  store/synthesis spine, and
- add Redis only where it belongs — backing `TCQ[["time capsule queue"]]` and
  `UIQ[["ui_queue"]]` (the §4 bearings), plus an optional cache node in front of
  the swarm's `REL`/recall step.

---

## 2. Redis backend data structure — what memories are stored AS

Redis stores vectors + metadata in **Hashes or JSON documents**, indexed by the
Redis Query Engine (RediSearch). Two vector index types: **FLAT** (exact/brute-force
KNN) and **HNSW** (approximate ANN). Distance metrics: **COSINE, L2, IP**. Supports
KNN, vector range queries, and metadata filtering / hybrid search. Redis treats
vectors as "a data type within its broader database, not a standalone vector-only
store." So: **flat vector + metadata, no native graph.**
- https://redis.io/docs/latest/develop/ai/

**Native graph capability — gone.** RedisGraph was deprecated; last major release
was 2.12, with maintenance committed only **until end of January 2025**, after
which it is EOL. Redis chose not to replace it natively. The community fork
continuing the RedisGraph codebase is **FalkorDB** (a separate product, not Redis).
**Redis is no longer a graph DB.**

**RedisVL** (the Python client): pure vector tooling — vector index,
`SemanticCache`, and `SemanticMessageHistory` (role-based chat history retrievable
by recency or vector similarity). It imposes **no episodic/semantic memory
typing** — these are practical utilities for LLM context management, not formal
memory classifications.
- https://github.com/redis/redis-vl-python

---

## 3. Redis Agent Memory Server — the deepest dive

https://github.com/redis/agent-memory-server — built on RedisVL / Redis Query
Engine.

**Two-tier model:**
- **Working memory** (session-scoped): messages, structured memories, summary of
  past messages, metadata.
- **Long-term memory** (persistent, cross-session): semantic / keyword / hybrid
  search, topic modeling, entity recognition, deduplication. Stored as **embedded
  vectors + metadata records.**

**It DOES impose a memory-type taxonomy.** From `agent_memory_server/models.py`:

```python
class MemoryTypeEnum(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    MESSAGE  = "message"
```

`MemoryRecord` fields include: `id` (client-provided, for dedup/overwrite), `text`,
`memory_type`, `topics`, `entities`, `event_date` (when the described event
occurred), `namespace`, `user_id`, `session_id`, `created_at`, `updated_at`,
`pinned`, `extraction_strategy`.

**Extraction strategies** (configurable): **discrete** (individual facts),
**summary** (condensed overviews), **preferences** (user-preference extraction),
**custom** (developer-defined). All produce **flat typed records**, not graph
nodes/edges.

**Graph edges? No.** `entities` and `topics` are **metadata fields on each flat
record**, not traversable relationship edges between memories. Linking/retrieval is
vector similarity + metadata filtering. There is no edge structure: **purely vector
+ typed metadata flat records.** It has episodic/semantic *typing* and an *entities
field*, but it is not a graph and does no relationship modeling.

---

## 4. Mem0's structure — note: it changed

The classic story is mem0 = vector + graph + KV hybrid. **That is now outdated for
the OSS SDK.** Current docs / migration guide:

> "External graph store support has been removed from the open-source SDK and
> replaced by built-in graph memory (entity linking), which runs natively with no
> external dependencies."

Removed: `enable_graph` / `graph_store` config blocks for Neo4j, Memgraph, Kuzu,
Apache AGE, Neptune. Now mem0 extracts entities (proper nouns, quoted text,
compound noun phrases) during the add pipeline and stores them in a **parallel
vector collection (`{collection}_entities`) inside the same vector store**.
Memories sharing entities are linked via **retrieval ranking boosts**, not an
exposed traversable graph — the old `relations` field is no longer returned. So
current OSS mem0 ≈ **vector-store-only with entity-vector linking** (semantic +
BM25 keyword + entity matching fused). Memory-type labels in docs: episodic
("summaries of past interactions"), semantic ("relationships between concepts"),
factual ("preferences, account details, domain facts") — stored in a unified
layered (conversation/session/user/org) vector architecture, not physically
separated stores.
- https://github.com/mem0ai/mem0
- https://docs.mem0.ai/open-source/graph_memory/overview
- https://docs.mem0.ai/core-concepts/memory-types

> **Uncertainty:** I could not confirm whether mem0's **hosted/Platform** product
> still offers a managed graph option distinct from the OSS SDK (search was
> transiently unavailable). The removal above is documented for the **open-source
> SDK**. Treat "mem0 = hybrid graph" as deprecated for OSS, unverified for hosted.

**Can Redis be mem0's backend?** Vector-store backend only (mem0 supports many
vector stores incl. Qdrant; Redis is usable as one). Since mem0 no longer uses an
external graph store at all, the question is moot — there is no graph part to back,
and RedisGraph being dead is irrelevant to current mem0.

---

## 5. Zep / Graphiti — the graph-native end

https://github.com/getzep/graphiti — a **temporal (bi-temporal) knowledge graph.**
Four elements: **Entities (nodes)** with evolving summaries; **Facts/Relationships
(edges)** as Entity→Relationship→Entity triplets with validity windows; **Episodes
(provenance)** = raw ingested data each derived fact traces back to; **Custom Types**
(Pydantic ontology). Bi-temporal: tracks when a fact became true and when
superseded, with automatic fact invalidation (facts preserved, not deleted).
Hybrid retrieval = semantic embeddings + BM25 + graph traversal. Backends: **Neo4j
(primary), FalkorDB, Amazon Neptune (+OpenSearch), Kuzu (deprecated).** This is the
true graph-DB end of the spectrum, and the system Recall would reach for if it ever
wanted real traversable entity relations with valid-time.

---

## 6. Comparison table

| System | Backend structure | Episodic vs semantic typing | Entity/relationship modeling | Reflection/synthesis (NEW cross-memory insight?) | Where it sits |
|---|---|---|---|---|---|
| **Redis (raw / RedisVL)** | Vector (FLAT/HNSW) + metadata in Hash/JSON; **no graph** (RedisGraph EOL Jan 2025) | **No** — RedisVL imposes none | No (vector + metadata only) | **No** | Pure store / infra primitive |
| **Redis Agent Memory Server** | Vector + typed metadata flat records (built on RedisVL) | **Yes** — `MemoryTypeEnum`: episodic/semantic/message | `entities` + `topics` as **metadata fields only**; **no edges/graph** | **No** (extracts/dedupes/summarizes; no belief synthesis) | Store + light typing & extraction |
| **Mem0 (current OSS)** | **Vector-only** + parallel `_entities` vector collection (was hybrid; graph store removed) | Yes (episodic/semantic/factual labels in unified vector layers) | Entities extracted + linked via **ranking boost**, not traversable edges | No (extraction/dedup; no reflection) | Store + retrieval-time linking |
| **Zep / Graphiti** | **Graph DB** (Neo4j/FalkorDB/Neptune); bi-temporal | Episodes (episodic) + entity/fact nodes (semantic), explicit | **Yes** — true nodes + typed edges + temporal validity | Partial (fact invalidation, evolving entity summaries; not principle synthesis) | Graph-native store + temporal reasoning |
| **Hindsight (ours)** | **Vector** (Postgres + pgvector ANN) | **Yes** — 4 networks: World facts (semantic), Experiences (episodic), Entity summaries, Evolving beliefs | Entity resolution + entity summaries; beliefs as a network (not a property graph) | **Yes** — REFLECT step synthesizes non-obvious cross-memory connections + principles; strict evidence/inference separation | **Cognitive layer** on a vector store |

**Spectrum:** raw Redis (pure infra) → Redis Agent Memory Server / mem0 (vector
store + typing/extraction) → Hindsight (vector store + full cognitive pipeline +
reflection) → Graphiti (graph-native + temporal). Hindsight and Graphiti are the
only two doing real structure beyond flat records; **only Hindsight generates
genuinely new synthesized beliefs/principles** — which is exactly the principles
rung the flywheel is built around.

---

## 7. Sources

- Redis AI / vectors: https://redis.io/docs/latest/develop/ai/
- RedisVL (SemanticCache, SemanticMessageHistory): https://github.com/redis/redis-vl-python
- Redis Agent Memory Server: https://github.com/redis/agent-memory-server
- Mem0 repo: https://github.com/mem0ai/mem0
- Mem0 graph memory: https://docs.mem0.ai/open-source/graph_memory/overview
- Mem0 memory types: https://docs.mem0.ai/core-concepts/memory-types
- Graphiti: https://github.com/getzep/graphiti

**Uncertainty flags:** the RedisVL `semantic_caching` user-guide URL 404'd
(mechanism confirmed via the redis-vl-python repo instead); mem0 hosted/Platform
graph status unverified (OSS removal is confirmed); the RedisGraph EOL date (end of
Jan 2025) and FalkorDB-as-fork came from search summaries rather than a fetched
Redis EOL page — directionally certain, worth a second check before quoting
formally.
