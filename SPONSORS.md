# RETURN — Sponsor & Track Playbook (Cal Hacks 2026)

Hour-0 reference. Per-sponsor deep dives (offer · prize/criteria · workshop · concrete
RETURN integration · how to win). **This rev re-swept *all* ~31 sponsor/cohost Slack
channels** (not just the original 10), so it covers tracks the earlier doc never mentioned
(Browserbase, TokenRouter, Pika, Cognition/Devin, Terac, …) and corrects stale entries.

> **Provenance of this doc:** each sponsor below is tagged with how fresh its data is:
> **[SLACK-VERIFIED]** = read live from the sponsor's channel this sweep (2026-06-21);
> **[PRIOR-PASS]** = retained from the previous web+Slack research pass, **not** re-read
> this sweep because the Slack API was timing out under concurrent load — trust but
> re-confirm at the booth; **[COULD-NOT-VERIFY]** = channel timed out on every attempt and
> we have no reliable data — listed so they aren't silently dropped, not as a recommendation.

> **Three corrections vs. the previous doc:**
> 1. **ElevenLabs is NOT a confirmed sponsor.** Its channel has no rep, no offer, no prize —
>    only hackers asking for credits, one explicitly noting *"elevenlabs isn't even a sponsor
>    of this event… I can't see their logo anywhere."* The old "ElevenLabs > Deepgram, voice
>    cloning hero beat" plan is **dead** — **Deepgram is the voice lane.**
> 2. **The field is much bigger than 10.** Real, previously-undocumented cash/credit tracks:
>    **Browserbase $2,000**, **TokenRouter $1,000/$500/$300**, **Pika 5k+5k credits**,
>    **Cognition/Devin** (memory-layer track), **Terac $1,000 + $250 credits/team**.
> 3. **Anthropic channel id was wrong** in the research dispatch (`C0B7SFEQ2FL` is the intro
>    channel). The real one is **`#spons-anthropic` = `C0B7SJ4U10S`** — $25 self-serve credits
>    link still live; mentors Tyler Lacroix & Marcus Wong at the Claude booth.

---

## What we actually built (so "fit" claims are honest)

The integration stories below are grounded in the **principle pipeline that exists on the
`aaryan-principles` branch**, not the north-star flywheel. What's real:

- **The raw→principles ladder (v0).** `Event` (canonical per-item type) → **gap-segment**
  per source into `Unit`s (`pipeline/segment.py`, zero LLM) → **render + Hindsight retain**
  into one Postgres/pgvector bank (`pipeline/render.py`; self→Experience, others→World via
  tags) → **cluster-first minting** of principles (`pipeline/mint.py`).
- **Rung ③ minting is cluster-first** (`docs/rung3-minting-strategy.md`): recall a memory
  pile, cluster by Hindsight's own embeddings, drop singletons, one LLM call per cluster
  proposing a one-line principle citing ≥2 `memory_id`s, then **non-LLM citation
  verification** (cited id must be in the cluster) + an **embedding novelty check** + a
  **ledger-derived confidence** (never the LLM's self-report).
- **Rung ④ is a principle *graph*** (`core/principle.py`): typed grounded edges
  (`supports/refines/generalizes/contradicts`), each with its own evidence ledger drawn
  from a bounded memory-layer neighborhood.
- **Memory-quality enrichments** (latest commits): contacts handle→name join, photo
  **vision** captions via a cheap OpenRouter vision model (local thumbnails, 30-day window),
  spotify artist-vibe cache, and a retain-prompt slang guard.
- **Inference:** OpenRouter only (`gemini-3.5-flash` for retain/mint, `qwen3-embedding-8b`
  truncated to 2000-dim for vectors, Claude models available). No local model loads.

So the honest one-liners: our pipeline is a **multi-step LLM chain** (→ observability/eval
tracks: Arize, Sentry), it **routes everything through one OpenRouter-compatible endpoint**
(→ TokenRouter near-drop-in), it has a **vision pre-pass** (→ media tracks), and it is a
**persistent memory layer with provenance** (→ Devin memory-layer track). The agentic swarm
and contradiction flywheel are **NOT built** — don't pitch fit that depends on them (Fetch
swarm, etc.) as if it exists.

---

## Grand prize (pick ONE at Devpost submission)

🏆 **Ddoski's World — $5,000.** Consumer / social / real-world apps. RETURN (location-based
memory + wellbeing) is the natural fit. Overall judging = **Impact · Functionality ·
Technical Complexity · Creativity.** Strengths are Impact + Creativity; make the working
demo (Functionality) and the **principle-graph engine** (Technical Complexity) *visible* —
the cluster-first minting + grounded edges *is* the technical-complexity story.

## Sponsor prizes — priority order (by reward × fit × confirmed-effort)

| Sponsor | Prize | Status | Effort | Why it fits RETURN |
|---|---|---|---|---|
| **Anthropic** ⭐ | Tungsten Cube + **$5,000 API credits** (Best Use of Claude) | PRIOR-PASS track / SLACK-VERIFIED credits | Low | Claude is our model. Name caching the principle-graph context, structured-output minting, Batch ingestion. Build with Claude Code. |
| **Browserbase** 🆕 | **$2,000 cash** (Best Use of Browserbase) | SLACK-VERIFIED | Med | Browser-automation ingestion adapter for a web-only source (Claude.ai export, Spotify web) → feeds the same `Event`→principle pipeline. Highest single cash prize. |
| **The Token Company** | **$2,000** + Claude Max 6mo/member + interview | PRIOR-PASS | Low–Med | Compress the large recalled-memory + principle-graph context fed to minting/REFLECT. Compounding savings. |
| **TokenRouter** (PaleBlueDot) 🆕 | **$1,000 / $500 / $300** (credits) | SLACK-VERIFIED | **Low** | We already call an OpenRouter-compatible endpoint — TokenRouter is a base-URL+key swap. Pitch: **Zero-Data-Retention routing for personal memory data**. |
| **Fetch.ai** | **$1,500 / 1k / 500** + interviews | PRIOR-PASS | Low–Med | Stackable, mandatory product use. Wrap RETURN's recall as one discoverable uAgent on ASI:One (Chat Protocol). |
| **Terac** 🆕 | **$1,000** most-creative + $250 credits/team | SLACK-VERIFIED | Med | "MCP for human labor." Hire humans to label whether a minted principle is *actually true of the user* → measurable before/after on principle quality. Maps onto our ledger. |
| **Arize** | ~$1,000 (booth-judged) | PRIOR-PASS | Low | Observability/eval over the multi-step minting chain. Groundedness evaluator over principle citations → measured improvement. |
| **Cognition / Devin** 🆕 | Named track (amount TBC) | SLACK-VERIFIED | Med | Judge said a **memory layer / MCP server that extends Devin** is *favorable*. RETURN's principle pipeline **is** a persistent memory layer — expose it as an MCP Devin can query. |
| **Pika** 🆕 | 5k+5k credits (Best creative use of Pika MCP) | SLACK-VERIFIED | Med | "Bring a reconstructed moment to life": feed a minted principle / moment to Pika MCP → short video capsule. Strongest *visual* demo beat. |
| **Sentry** | Switch 2 + guaranteed interview | PRIOR-PASS | Low | Best Use of SDK; one distributed trace browser→FastAPI→`gen_ai.*` spans over the pipeline. Bonus for observability. |
| **Deepgram** | Switch 2 | SLACK-VERIFIED | Med | Voice "talk to past you" — STT (Nova-3) + TTS (Aura-2) + Voice Agent. Voice must be *core*. **This is the voice lane** (ElevenLabs is out). |
| **Simular / Sai** | $500/member | SLACK-VERIFIED | Low–Med | SimuLang as a GUI ingestion layer; or just use Sai to generate the demo video (one-prompt) — cheap way to claim the per-member payout. |
| **Redis** | TBC (confirm at booth) | PRIOR-PASS | Low | **SemanticCache only**, and only if we measure a repeat-query rate. Vector/queues/graph are redundant or premature — out of v1. |
| **Poke** (Interaction Co) | None posted (thematic) | SLACK-VERIFIED | Low | Surface a reflection into the user's real iMessage thread via the SEND API. Memorable beat, but **no prize** → low priority. |
| **Runpod** | None posted | SLACK-VERIFIED | — | GPU host *if* we ever self-host inference (privacy/local-Gemma north-star). No track posted. Ask reps for credits. |

**Voice decision (revised):** **Deepgram leads the voice lane.** ElevenLabs is no longer a
participating sponsor, so "past self in your own cloned voice" can't win an ElevenLabs prize
(there isn't one); if you want voice cloning for the hero beat it's a generic capability, not
a track. Keep voice on Deepgram end-to-end to stay eligible for their Switch 2.

**No fit / skip (verified):** **QNX** (embedded hardware + Raspberry Pi, zero software
overlap), **Cognichip** (chip-design EDA), **HRT** (quant trading, no track), **Zoox**
(autonomous vehicles), **Skydeck** / **The House Fund** (VC/accelerator — relationship, not a
prize track; worth a Sunday conversation if fundraising), **Overshoot** (rep no-show),
**Context** (channel empty), **Annapurna** / **Fieldguide** (track "coming soon", never posted
as of this sweep).

---

## 1. ANTHROPIC — "Best Use of Claude" — **Tungsten Cube + $5,000 API credits** · [PRIOR-PASS track / SLACK-VERIFIED credits]

**Channel:** `#spons-anthropic` = **C0B7SJ4U10S** (the intro channel `C0B7SFEQ2FL` is a
different channel — don't confuse them).

**Track (Devpost, prior pass):** Claude is a *co-host*. Criteria reward Claude **Code** usage
explicitly: (1) Technical Complexity (innovative use of Claude Code beyond basics), (2)
Creative Use Case, (3) Impact & Practicality. Competitive.

**Credits (Slack-verified this sweep):** **$25** self-serve, near-instant —
`https://claude.com/offers?offer_code=fb3203ec-b5d7-48a4-ab38-5fe5d9bcd026`. A separate
**.edu credits** program exists; apply from a **personal account on your school email** (an
account under an org plan whose owner lacks an `.edu` email gets rejected — confirmed by a
hacker hitting exactly that). Mentors **Tyler Lacroix [Mentor/Anthropic] (@tylerlacroix0)**
and **Marcus Wong (@manhinwong)** — DM them or hit the **Claude booth**. Workshop slides
(approx): a Google Slides deck linked in-channel.

**Models (exact IDs):** `claude-opus-4-8` ($5/$25 per 1M, 1M ctx) — REFLECT/mint; `claude-
sonnet-4-6` ($3/$15) — high-volume extraction; `claude-haiku-4-5` ($1/$5) — cheap classify.

**Integration (the cost-engineering *is* the story):**
- **Minting → Claude + prompt caching.** The recalled cluster + principle-graph context is a
  large stable prefix re-sent per cluster → put it first with `cache_control:{type:"ephemeral"}`.
- **Structured-output minting.** Have the proposer return typed `{principle_text, cited_ids}`
  via `json_schema` → our non-LLM citation verifier consumes it deterministically.
- **Batch ingestion** (50% cheaper) on Sonnet/Haiku for the chat.db backfill.
- **Build with Claude Code and say so.** Cross-check exact model prices against the
  `claude-api` skill before quoting.

**Win:** demo a live minted principle the user never stated (Creative + Technical at once);
name the Claude features in the pitch.

---

## 2. BROWSERBASE 🆕 — "Best Use of Browserbase" — **$2,000 cash** · [SLACK-VERIFIED]

**Channel:** `#spons-browserbase` = C0B8LT0ASBA. **Prize:** $2,000 cash (highest single cash
prize in the field). **Criteria:** "best use of Browserbase" — no finer breakdown posted
(per @shrey, Browserbase). **Mandatory product use:** yes.

**Offer:** promo code **STARTERPACK** on the free Developer plan at browserbase.com.
**Workshop:** Sat 5pm — "build a browser agent in <15 min" (Shake Shack provided). **Rep:**
@shrey (table or DM).

**Integration (Med):** Browserbase = cloud headless browser (Playwright-in-the-cloud). Add a
**browser-automation ingestion adapter** for a source with no clean export — log into a
web app, scrape the user's own data, normalize to our canonical `Event`, and let it rise
through the *same* segment→retain→mint pipeline. Cleanest target: auto-pull a **Claude.ai
chat export** or **Spotify web** history via the browser, persisting through
`storage/persist.py` like every other adapter. Demo: "we point Browserbase at a web source
we have no API for, and seconds later a principle traces back to it."

**Win:** show one real web source ingested end-to-end with provenance intact to the scraped page.

---

## 3. THE TOKEN COMPANY — Compression — **$2,000 + Claude Max 6mo/member + interview** · [PRIOR-PASS]

> Not re-read this sweep (channel timed out). Re-confirm details at the booth.

**Prize (prior pass):** 1st $2,000 + Claude Code 5× Max (6mo) per member + boosted MTS
interview; 2nd $1,000. Challenge: build a system that **compresses LLM inputs while preserving
useful information** — they reward creative approaches, not only calling their API.

**Product:** drop-in compression API (deterministic token deletion). `pip install
the-token-company`; wrap an Anthropic client with `with_compression(...)`; `aggressiveness`
0.05–0.8; wrap exact IDs/quotes in `<ttc_safe>…</ttc_safe>`.

**Integration (highest-ROI first):**
- **(A) Minting/REFLECT context** — compress the recalled memory pile + principle-graph
  context at `aggressiveness≈0.2`, `<ttc_safe>` the `memory_id`s and exact quotes (the
  ledger must survive verbatim — our non-LLM citation check fails if an id is mangled).
- **(B)** Per-cluster proposer calls compress → savings compound across clusters.
- **Winning edge:** a live cumulative `tokens_saved` dashboard + raw-vs-compressed Claude
  output side-by-side proving the minted principle is unchanged.

---

## 4. TOKENROUTER (PaleBlueDot AI) 🆕 — "Best Use of TokenRouter" — **$1,000 / $500 / $300** (credits) · [SLACK-VERIFIED]

**Channel:** `#spons-palebluedot-ai` = C0B7W79BH60. **Prize:** 1st $1,000 · 2nd $500 · 3rd
$300, paid as TokenRouter credits. **Criteria:** meaningfully use TokenRouter as your LLM
routing layer (not spelled out further). **Mandatory:** yes. **Rep:** @christine.dai.

**Offer:** **$50** hacker credits/person via the redemption Apps-Script link in-channel
(vouchers ran out ~05:23 PT 06-21 → **DM @christine.dai** for more). TokenRouter pitch: no
platform fee (vs OpenRouter's ~5.5%), RBAC, audit logs, **Zero Data Retention by default**;
backed by PaleBlueDot ($150M raise, >$1B val).

**Integration (Low — near drop-in):** RETURN already routes **all** inference through one
OpenRouter-compatible endpoint (`runtime/hindsight.py` sets `LLM_PROVIDER`/base URL +
`OPENROUTER_API_KEY`). TokenRouter is API-compatible → swap base URL + key. **The pitch writes
itself:** *"a personal-memory app ingests your iMessage — Zero-Data-Retention routing means
your raw data never lands in a third-party log."* That's a real architectural argument, not a
forced integration. Best effort-to-reward ratio in the field.

**Win:** show the one-line config swap + the ZDR/audit-log story for sensitive personal data.

---

## 5. FETCH.AI — "Best Use of Agentverse" — **$1,500 / $1,000 / $500 + interviews** (mandatory, stackable) · [PRIOR-PASS]

> Not re-read this sweep (channel timed out). Re-confirm at the Tilden workshop/booth.

**Prize/criteria (prior pass):** $3,000 pool + internship interviews. Rubric: Functionality
25% · Use of Fetch Tech 20% · Innovation 20% · Real-World Impact 20% · UX 15%. **Using the
product is MANDATORY** — agents on Agentverse + **Chat Protocol**, core must work through
**ASI:One**. **Stackable** with a Ddoski grand prize.

**Access:** promo `BERKELEYAIAV`; `pip install uagents`; ASI:One API `https://api.asi1.ai/v1`.

**Integration (thin):** wrap RETURN's **recall + principle query** as **one "RETURN Memory
Agent" uAgent** whose `ChatMessage` handler calls our existing pipeline (`pipeline/show.py`
recall + the minted principle graph). MVP ≈ 1 file (`mailbox=True,
publish_agent_details=True`, `Protocol(spec=chat_protocol_spec)`). **Do not** pitch the
retriever/critic/arbiter swarm as agents — that swarm is **not built**.

---

## 6. TERAC 🆕 — "MCP for Human Labor" — **$1,000 most-creative + $250 credits/team** · [SLACK-VERIFIED]

**Challenge (verbatim, @jack / Terac, cross-posted):** *"Use Terac to recruit real humans,
collect feedback on something in your project, use that data to improve it, demonstrate a
measurable before-and-after."* Each team gets **$250 in Terac annotation credits**; **$1,000
to the most creative team.** **Judging:** Model Improvement 40% · Annotation Environment 35% ·
Use of Human Data 25%. Docs: terac.com/mcp, terac.com/docs/researchers/mcp/install.

**Integration (Med — and a genuinely strong fit for our provenance story):** the hardest open
problem in our pipeline (`docs/rung3-minting-strategy.md`) is **behavioral corroboration** —
telling a real principle from a fluent confabulation, which has *no labeled ground truth*.
Terac supplies exactly that: **hire humans to label whether each minted principle is actually
true of the user**, feed those labels back as `weakens`/`supports` rows into the evidence
**ledger**, recompute confidence, and show **principle precision before vs. after**. That is a
clean, measurable before/after that hits all three judging axes — and it stays inside the
§2 invariant (the labels are high-priority evidence rising through the ledger, not a principle
written directly).

**Win:** before/after principle-quality table driven by real human labels routed through the ledger.

---

## 7. ARIZE — observability/eval — **~$1,000 (booth-judged)** · [PRIOR-PASS]

> Not re-read this sweep (channel timed out). Re-confirm at the booth.

**Win condition (prior pass):** judged at the **booth**. Show (1) live **traces** of the
pipeline in an Arize project, (2) ≥1 custom **evaluator**, (3) a concrete *"measured X, changed
Y, X improved"* story.

**Integration:** OpenRouter is OpenAI-compatible → auto-traced by the OpenAI instrumentor.
```python
# import FIRST
from phoenix.otel import register
tp = register(project_name="return-pipeline", auto_instrument=True, batch=True)
tracer = tp.get_tracer(__name__)
@tracer.chain
def mint_cluster(cards): ...        # rung ③ per-cluster proposer
@tracer.chain
def reflect_synthesis(memories): ... # REFLECT
```
**Evaluator:** principle-citation **groundedness** — does each cited `memory_id` actually
support the minted text? (LLM-judge over real mint traces.) **Booth story:** "minting cited
weakly-related memories; we ran a groundedness evaluator over ~50 mint traces, found ~30%
unsupported, tightened the cluster cosine threshold + added the novelty check, re-ran:
groundedness → ~90%. Two trace sets side by side."

---

## 8. COGNITION / DEVIN 🆕 — "Most technically impressive project built with Devin" · [SLACK-VERIFIED]

**Channel:** `#spons-cognition` = C0B7W7K830U. **Prize amount not posted in Slack** (merch +
extra credits for workshop attendees). **Criteria (verbatim, @albert.chen):** *"The main
criteria is that you build using Devin, but we may be favorable if you integrate / extend
Devin in the project itself."* He confirmed to a hacker that **building a memory layer / MCP
server that extends Devin qualifies** and is favored. **Mandatory:** build using Devin.

**Access:** **Devin Cloud** = workshop-attendees only (both workshops now past → window
likely closed). **Devin Desktop + CLI** = open to all via form (forms.gle/tau3o9s2MwAagEow5),
accounts provisioned ~30 min. **Reps:** @albert.chen, @katie.

**Integration (Med):** two angles — (1) use Devin Desktop/CLI to write RETURN's code; (2) the
stronger one — **expose RETURN as a memory MCP server Devin can query.** Our principle pipeline
(segment → retain → cluster → mint → graph) **is** a persistent, provenance-carrying memory
layer; an MCP endpoint that returns "principles + evidence for this person" is exactly the
"extend Devin with a memory layer" the judge said they favor.

**Win:** Devin calling our memory MCP and getting back grounded principles, live.

---

## 9. PIKA 🆕 — "Best creative use of Pika MCP" — **5,000 + 5,000 credits** · [SLACK-VERIFIED]

**Channel:** `#spons-pika` = C0B7L7VSFH9. **Track:** Best creative use of Pika MCP (@yutian
jessie.ma). **Credits:** 5,000 for signup + joining the track (Google Form in-channel),
another 5,000 for the workshop, extra for sharing a build in-channel. **Steps to get credits:**
onboard at pika.me → connect Pika MCP to your agent/Claude Code → finish agent authorization.
**Mandatory:** yes. **Reps:** @yutianjessie.ma, @emma.

**Integration (Med — strongest *visual* demo hook):** after a principle/moment is minted, call
Pika MCP to generate a short **video capsule** representing it (e.g. "late-night creative
sprints with close friends"). Makes the abstract principle tangible on stage. Wire the MCP from
the FastAPI backend or a Claude Code session post-mint.

**Win:** principle → 10-second generated capsule, shown live as the "bring your memory to life" beat.

---

## 10. SENTRY — Best Use of SDK — **Switch 2 + guaranteed interview** · [PRIOR-PASS]

> Not re-read this sweep (channel timed out). Re-confirm at the booth.

**Criteria (prior pass):** strong technical execution + clear communication + teamwork;
**bonus for observability/error monitoring.** Free account suffices.

**Integration:** `sentry-sdk[fastapi]` on the backend; `AnthropicIntegration(include_prompts=
True)`. OpenRouter calls aren't auto-instrumented → emit manual `gen_ai.*` spans so the **AI
Agents dashboard** lights up over the minting chain. Frontend `@sentry/react` +
`tracePropagationTargets` → **one distributed trace** browser→FastAPI→mint spans.
**Demo:** click "mint" in React → single waterfall trace → force a failed extraction → it
surfaces with the exact LLM input → Seer root-causes it.

---

## 11. DEEPGRAM — voice experience — **Nintendo Switch 2** · [SLACK-VERIFIED]

**Channel:** `#spons-deepgram` = C0B7L7SLN2F. **Prize:** Switch 2 for the *"most creative &
well-executed voice-powered experience."* **Criteria (verbatim, @naomi.carrigan):** use ≥1
Deepgram voice product (STT/TTS/Voice Agent) as the **CORE** experience, "not just an
afterthought." Judged on creativity · how fundamental voice is · technical execution.
**Mandatory:** yes.

**Offer:** **$200** credits at https://dpgr.am/ucb-ai-signup (Nova-3 STT, Aura-2 TTS, Voice
Agent). Docs dpgr.am/ucb-ai-docs; Discord dpgr.am/ucb-ai-discord. **Workshop:** Sat 2–3pm
(STT→LLM→TTS on one WebSocket — exactly our "talk to past you" loop). **Mentor:** @naomi.carrigan.

**Integration (Med, voice as core):** **Nova-3 STT** → spoken reflections become `Event`s that
feed the same pipeline; **Aura-2 TTS** → voice the past-self answer; **Voice Agent API** → the
"talk to past you" loop with `think.prompt` built from the principle-graph snapshot at that
timestamp. **This is the voice lane** now that ElevenLabs is out.

**Win:** speak a capsule live (transcribe + sentiment), then ask your past self aloud and hear
it answer grounded only in that snapshot.

---

## 12. SIMULAR (Sai / SimuLang) — **$500/member** · [SLACK-VERIFIED]

**Channel:** `#spons-simular` = C0B7SJKM6R0. **Prize:** ~$500/team-member; criteria at
sai.work/prize; must meaningfully use **Sai or SimuLang**. Eligibility chores: follow Sai on
socials, post with the tag, email screenshots to zening@simular.ai. **Reps:** @zening, @jiachen.

**Access:** 2-day unlimited trial via an **invite code** (capacity-limited, get one **in
person** at booth/workshop). **Workshop:** Sat 12–1pm, Floor 2 — headline demo is literally
*"orchestrate Claude Code in iMessage."*

**Integration (Low–Med):** **SimuLang** = "Playwright for the desktop" (Claude Code skill) → a
GUI ingestion layer for apps with no export (Notes, Photos captions) that POST to our
ingest path. **Caveat:** Sai's hosted desktop is **Windows**, so macOS chat.db work stays a
local daemon — use Sai for the **one-prompt demo video** (cheap way to claim the per-member
payout even if SimuLang ingestion doesn't land).

---

## 13. REDIS — credits $50 (`CALHACKER2026`) — **prize TBC** · [PRIOR-PASS]

> Not re-read this sweep (channel timed out). Confirm whether a prize exists at the booth.

**Architecture verdict (`docs/raw-to-principles-research.md` §4): Redis is OUT of v1.** The
vertical runs on SQLite + Postgres/pgvector via Hindsight. Per capability: vector search
**redundant** (pgvector), Agent Memory Server **redundant+weaker** (Hindsight synthesizes),
Streams **premature** (single-user volume), graph **dead** (RedisGraph EOL 2025-01-31). **The
one defensible play:** RedisVL **`SemanticCache`** in front of recall — *and only after
instrumenting a repeat-query rate.* Be honest on stage: system latency ∝ hit-rate (~25–30% at
a 30% hit rate), not the "160×" marketing figure. Stating this boundary to judges signals
architectural judgment.

---

## 14. POKE (Interaction Co) — **no prize posted (thematic)** · [SLACK-VERIFIED]

**Channel:** `#spons-interaction-co` = C0B7SHD2090. **No prize/criteria anywhere in-channel.**
Access via DM **@claudia** (also @hannah, @nathanrhee). **Workshop:** Sat 2pm, Tilden Floor 5.
Poke = AI assistant in iMessage/WhatsApp/Telegram with a working SEND API.

**Integration (Low):** on a reflection event, POST to the Poke SEND API → the prompt lands in
the user's real iMessage thread. Memorable "no new app" beat — but **no prize → low priority**;
do it only if the core demo is already done.

---

## 15. RUNPOD — **no prize posted** · [SLACK-VERIFIED]

**Channel:** `#spons-runpod` = C0B7P7MH8JZ. Channel is participants asking for GPU credits with
**no rep reply**; no prize/criteria/workshop posted. **Fit:** only relevant if we ever
self-host inference (the north-star local-Gemma/privacy angle) — H200s could host it. Today we
use OpenRouter, so this is off-path. Ask reps directly about credits if pursuing.

---

## Appendix A — No fit / skip (verified)

| Sponsor | Channel | Why skip |
|---|---|---|
| **QNX** | #spons-qnx | Hardware/embedded track — must run QNX OS on a Raspberry Pi + Physical AI. Zero overlap with a pure-software memory app. Hardware loaned at workshop; mentor @john. |
| **Cognichip** | #spons-cognichip | AI chip-design EDA platform. No NLP/memory integration path. |
| **HRT** | #spons-hrt | Quant trading firm; channel is pure banter, no track posted. Likely recruiting-only. |
| **Zoox** | #spons-zoox | Autonomous vehicles. No fit. |
| **Skydeck** | #spons-skydeck | UC Berkeley accelerator — relationship/program, not a prize track. Mentor Peter Milford (@pmilford) at tables. Worth a chat only if seeking acceleration. |
| **The House Fund** | #spons-the-house-fund | Pre-Seed/Seed VC. No prize. RETURN fits their thesis — talk to Jeremy Fiance (@fiance) Sunday if fundraising. |
| **Overshoot AI** | #spons-overshoot-ai | Rep no-show; only participants pinging "where are you." No data. |
| **Context** | #spons-context | Channel verified empty (clean zero-row API response). |
| **Annapurna Labs** | #cohost-annapurna-labs | AWS silicon (Inferentia/Trainium). Track "coming soon," never posted as of this sweep. Watch for a criteria post. |
| **Fieldguide** | #spons-fieldguide | Audit/advisory AI. Hacker guide still says "Coming Soon"; no criteria posted. |

## Appendix B — COULD-NOT-VERIFY (Slack API timed out every attempt this sweep)

No reliable data was retrievable for these — listed so they aren't silently dropped, **not** as
recommendations. Re-check the channels directly when Slack load drops, or visit the booths.

| Sponsor | Channel | What we know / couldn't confirm |
|---|---|---|
| **Orkes** | #spons-orkes (C0B7P3W8CDT) | Workflow-orchestration platform (Conductor OSS). Channel timed out on history **and** search across 6+ attempts (bot may not be a member). Prize/criteria/credits/workshop/reps — all **unknown**. |
| **Armor-IQ** | #spons-armor-iq (C0B8LTVCF96) | AI/cybersecurity. Channel timed out on every attempt. All details **unknown**; likely no fit but unconfirmed. |
| **Midjourney** | #spons-midjourney (C0B7SHD3SUS) | Image generation. Channel timed out on history + search. Prize/criteria **unknown**. (A media track could pair with Pika as a "memory → image" beat — verify first.) |
| **Band** | #spons-band (C0B7QHA3X0E) | Channel timed out on every attempt. Product/prize **unknown**. |
| **Ultimate Fighting Bots** | #spons-ultimate-fighting-bots (C0B7UEEKGNM) | Robotics/combat-bots, almost certainly hardware. Channel timed out. Prize **unknown**; likely no fit. |
| **Terac** | #spons-terac (C0B7QH5QDT8) | *Channel itself* timed out, but Terac's full challenge was captured from a cross-post (see §6) — so Terac is **documented**, only its own channel was unreadable this sweep. |

> **Methodology note:** the original 10-sponsor doc was produced by isolated research agents
> over web + Slack. This sweep added the ~21 previously-undocumented channels via 5 parallel
> Sonnet subagents reading Slack. Concurrent load caused sustained `conversations_history`
> timeouts; `conversations_search_messages` was the working fallback for several channels. The
> [PRIOR-PASS] sponsors (Token Co, Sentry, Arize, Redis, Fetch) could not be re-read this
> sweep and are retained from the previous verified pass — re-confirm at their booths.

---

## Action items (Hour-0)

**Pick the lane:** Ddoski's World (grand) + **Anthropic** (core) are non-negotiable. Then the
near-free + high-confidence tier: **TokenRouter** (one-line swap, $1k), **Browserbase** ($2k
cash, one ingestion adapter), **Arize + Sentry** (observability over the minting chain),
**Terac** (human-labeled principle quality — fits our hardest open problem). **Pika** for the
visual beat; **Deepgram** if you commit to voice as core. **Cognition/Devin** if you expose
RETURN as a memory MCP.

- [ ] **Anthropic:** redeem $25; build with Claude Code; cache the principle-graph context.
- [ ] **TokenRouter:** DM @christine.dai for credits; swap base URL+key; ZDR pitch.
- [ ] **Browserbase:** code `STARTERPACK`; add one browser-ingestion adapter feeding the pipeline.
- [ ] **Terac:** grab $250 team credits; label minted principles; before/after precision table.
- [ ] **Arize:** trace `mint_cluster`/REFLECT; groundedness evaluator over citations; before/after.
- [ ] **Sentry:** `gen_ai.*` spans over the chain; one distributed trace; rehearse failure→Seer.
- [ ] **Pika:** onboard pika.me, connect MCP, principle → video capsule.
- [ ] **Deepgram (if voice):** $200 via dpgr.am/ucb-ai-signup; STT→LLM→TTS loop on the snapshot.
- [ ] **Cognition (optional):** Devin Desktop via form; expose RETURN as a memory MCP.
- [ ] **Simular (optional):** invite code in person; or just Sai-generate the demo video.
- [ ] **Fetch (if chasing):** promo `BERKELEYAIAV`; 1-file RETURN Memory uAgent on ASI:One.
- [ ] **Redis (out of v1):** confirm a prize exists at the booth; SemanticCache only if measured.

**Human-needed verifications (booth):** Token Co / Sentry / Arize / Redis / Fetch prize details
(channels timed out — retained from prior pass); the COULD-NOT-VERIFY channels in Appendix B;
Cognition prize amount; Pika/Browserbase exact judging breakdowns.
