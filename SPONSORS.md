# RETURN — Sponsor & Track Playbook (Cal Hacks 2026)

Hour-0 reference. Per-sponsor deep dives (offer · prize/criteria · workshop · concrete
RETURN integration · how to win), produced by isolated research agents using web + Slack.
Status: **all 10 briefs complete.**

> **Two corrections from the final briefs:**
> 1. **Anthropic has a NAMED track** ("Best Use of Claude": Tungsten Cube + **$5,000 API
>    credits**) — Claude is a *co-host*, not just an enabling sponsor. Real target, competitive.
> 2. **ElevenLabs > Deepgram for our hero feature** — only ElevenLabs does **voice cloning**,
>    so "hear your past self in *your own* voice" is only possible there. Deepgram can't clone.

---

## Grand prize (pick ONE at Devpost submission)

🏆 **Ddoski's World — $5,000.** Consumer / social / real-world apps. RETURN (location-based
memory + wellbeing) is the natural fit. Overall judging = **Impact · Functionality ·
Technical Complexity · Creativity.** Strengths are Impact + Creativity; make the working
demo (Functionality) and the principle-graph engine (Technical Complexity) *visible*.

## Stackable sponsor prizes — priority order

Many sponsors confirmed **stackable** with a Ddoski grand prize (Fetch explicitly; teams are
openly combining Anthropic+Sentry+Arize). Fetch is the **only track that *requires* using its
product**, and its core must work through ASI:One.

| Sponsor | Prize | Effort | Why it fits |
|---|---|---|---|
| **Anthropic** ⭐ | Tungsten Cube + **$5,000 API credits** + Applied-AI office hour | Low | "Best Use of Claude." Claude is our core model. Name the features (prompt caching, adaptive thinking, structured outputs, Batch API). Build with Claude Code. |
| **The Token Company** | **$2,000** + Claude Max 6mo/member + interview | Low–Med | Compress our overlapping REFLECT/swarm context. Compounding token savings. |
| **Fetch.ai** | **$1,500** / 1k / 500 + interviews | Low–Med | Stackable. Wrap RETURN's memory/swarm as a discoverable uAgent on ASI:One (mandatory Chat Protocol). |
| **Arize** | ~$1,000 | Low | Observability/eval over our multi-step LLM pipeline. Booth-judged on traces + evaluator + measured improvement. |
| **Sentry** | Switch 2 + guaranteed interview | Low | Best Use of SDK; bonus for observability. One distributed trace click→pipeline. |
| **Deepgram** | Switch 2 | Med | Voice "talk to past you" — STT/TTS/Voice-Agent. Voice must be *core*. |
| **ElevenLabs** | TBC (booth) | Med | **Voice cloning** = past self in your own voice. Our strongest voice fit; no track posted yet. |
| **Redis** | TBC (confirm at booth) | Low | **SemanticCache only**, and only if we measure a repeat-query rate. Vector/memory/queues are redundant or premature at single-user volume — out of v1. |
| **Simular/Sai** | $500/member | Med | Automate cross-app ingestion via SimuLang; Sai orchestrates RETURN over iMessage. |
| **Poke** | None (thematic) | Low | Send capsule nudges into the user's real iMessage. Memorable demo beat. |

**Voice decision (Hour-0):** if you commit to voice as a *core* interaction, **ElevenLabs is
the primary** (cloning enables the hero beat) and Deepgram is the fallback/STT layer. You
cannot win the ElevenLabs prize without keeping it end-to-end on ElevenLabs; you cannot win
Deepgram's without voice being fundamental. Pick one to lead.

---

## 1. ARIZE AI — observability/eval — **~$1,000**

**Win condition (verbatim from Laurie, Arize, in Slack):** judged at the **booth**, not on
stage. They want to see (1) live **traces** of RETURN's pipeline in an Arize project, (2) at
least one custom **evaluator**, (3) a concrete **"we measured X, changed Y, X improved"**
story. *"Your hack doesn't have to be finished to show that you used Arize."* Judging from
noon Sun Jun 21.

**Offer / tooling**
- Prize ~$1k. Use **hosted Arize AX** (app.arize.com) over local Phoenix — judges look at
  *your Arize environment* at the booth; a shared hosted project URL is easiest to show.
- Workshop slides: https://docs.google.com/presentation/d/1o6lvVAnHxbern869j0DCdCm69X0fxtWFI3U-rKFSY1w/edit
- Colab: https://colab.research.google.com/drive/1IubxfSOb4TQPlBMkSV--aQxfT-csml6S
- Skills repo: https://github.com/Arize-ai/arize-skills
- Workshop: Floor 2 (Ddoski's Classroom), ran ~2pm Sat — use Colab+slides. Mentor: **Laurie
  Voss (@lvoss)**, at booth all day.

**Integration (OpenRouter = OpenAI-compatible → auto-traced by the OpenAI instrumentor):**
```bash
pip install arize-phoenix-otel openinference-instrumentation-openai \
            openinference-instrumentation-anthropic
```
```python
# instrumentation.py — import FIRST, before openai/anthropic
from phoenix.otel import register
tp = register(project_name="return-pipeline", auto_instrument=True, batch=True)
tracer = tp.get_tracer(__name__)

@tracer.chain
def reflect_synthesis(memories): ...     # REFLECT cross-memory synthesis
@tracer.chain
def detect_contradiction(a, b): ...      # NLI alignment/contradiction
@tracer.tool
def retriever(query): ...                # swarm Retriever
@tracer.agent
def arbiter(candidate): ...              # swarm Arbiter
```
MCP for Claude Code: `claude mcp add arize-tracing-assistant uvx arize-tracing-assistant@latest`

**Evals to build (LLM-as-judge over real traces):** principle-extraction faithfulness;
contradiction-detection precision (catch false-positive contradictions sent to the user);
**REFLECT groundedness/hallucination** (most demo-able).

**Winning booth story:** "REFLECT was hallucinating beliefs unsupported by the memories. We
traced the pipeline in Arize, ran a groundedness evaluator over ~50 REFLECT traces, found
~30% unsupported (a cluster of low-groundedness spans), saw the retriever returning weakly-
related memories, tightened the retrieval threshold + added a grounding instruction, re-ran:
groundedness → ~90%. Here are the two trace sets side by side." (Screenshot before/after.)

---

## 2. SENTRY — Best Use of SDK — **Nintendo Switch 2 + guaranteed interview**

**Prize + criteria (verbatim, Stephanie Lipp, Sentry):** Switch 2 + guaranteed interview
(internship/new-grad). Judged on *"strong technical execution paired with clear
communication, collaborative problem-solving… how your team worked together under pressure.
**Bonus points if you leveraged observability or error monitoring.**"* → Lead with the
teamwork story; back it with a real observability story.

**Offer:** Free account is enough — **you do NOT need the GitHub Student plan** (mentor Ryan
Albrecht, Slack: *"it's about using the Sentry API, which you can do with a regular free
account… if you hit usage limits lmk and I'll fix it"*). Free hacker pack: 50K errors, 5GB
logs, $20 **Seer** AI-debugging credits, free 1yr. Sign up at sentry.io, grab DSN. Workshop
"How to fix bugs" Sat 5–6pm, Ddoski's Classroom. Mentors: @stephanie.lipp, @ryan.albrecht
(usage limits), @olegbezr. Get booth help **early** Sunday.

**Integration**
- Backend: `pip install "sentry-sdk[fastapi]"`
```python
import sentry_sdk
from sentry_sdk.integrations.anthropic import AnthropicIntegration
sentry_sdk.init(dsn="https://<key>@o<org>.ingest.sentry.io/<project>",
    traces_sample_rate=1.0, enable_logs=True, send_default_pii=True,
    integrations=[AnthropicIntegration(include_prompts=True)])
```
- OpenRouter/swarm calls aren't an auto-instrumented SDK → emit manual `gen_ai.*` spans so
  the **AI Agents dashboard** lights up:
```python
with sentry_sdk.start_span(op="gen_ai.invoke_agent", name="invoke_agent REFLECT") as s:
    s.set_data("gen_ai.agent.name", "REFLECT Synthesizer")
    with sentry_sdk.start_span(op="gen_ai.chat", name="chat claude-opus") as c:
        c.set_data("gen_ai.request.model", "anthropic/claude-opus")
        c.set_data("gen_ai.input.messages", json.dumps(messages))
        ...
```
- Frontend: `npm install @sentry/react`; set `tracePropagationTargets` to the API origin so
  **frontend + backend share ONE distributed trace** (the showpiece). Wrap in
  `Sentry.ErrorBoundary` (React 19: `reactErrorHandler`).

**Winning 60-sec demo:** (1) click "REFLECT" in React → show the single waterfall trace
browser→FastAPI→`gen_ai.invoke_agent`→Claude `gen_ai.chat`+extraction spans, point at the
slow span. (2) Force a failed extraction → it surfaces with breadcrumbs + the exact LLM input
that broke it → let **Seer** root-cause it ("we didn't stare at a terminal for 2 hours" =
their workshop pitch). (3) Token/cost per swarm agent in the AI Agents view. (4) Narrate how
the team split the work — they literally judge that.

---

## 3. THE TOKEN COMPANY — Compression Challenge — **$2,000 + Claude Max 6mo/member + interview**

**Prize (verbatim, Taaha):** 1st $2,000 + Claude Code 5× Max (6mo) for every member +
boosted MTS interview; 2nd $1,000. Challenge: *"Build any system… that compresses LLM inputs
while preserving useful information"* — they reward **building/creative approaches** to
context optimization/retrieval/encoding, not only calling their API. (Full criteria doc is
login-gated — open it signed-in or ask Taaha.)

**Product:** drop-in prompt/context **compression API** (deterministic token deletion, not
summarization). Models bear-1/1.1/**bear-2**; ~10–40% token reduction at flat accuracy
(light compression can *raise* accuracy). Free tier = first **50M input tokens free**.
```bash
pip install the-token-company   # key format ttc-...
```
```python
from anthropic import Anthropic
from thetokencompany.anthropic import with_compression
client = with_compression(Anthropic(api_key=KEY), compression_api_key="ttc-...")
# system + user msgs auto-compressed; assistant msgs passthrough (preserves prompt caching)
```
`aggressiveness` 0.05–0.2 for content the model answers from, 0.5–0.8 for background;
wrap IDs/exact quotes in `<ttc_safe>…</ttc_safe>` (never compressed). Workshop Sat 6pm,
Floor 5 Tilden. Contacts: Taaha Khan, Rasmus. Booth = front corner of main room.

**Integration (highest-ROI first):**
- **(A) REFLECT** — compress recalled facts + principle-graph context at `aggressiveness=0.2`,
  `<ttc_safe>` principle IDs + exact quotes. Biggest single win.
- **(B) Swarm Critic/Retriever** — use `with_compression(...)` so every agentic-loop call is
  compressed → savings compound across iterations.
- **(C) "Talk to past you" temporal snapshots** — large, self-redundant; compress at 0.5–0.7.

**Winning edge:** a **live cumulative token-savings dashboard** across a full RETURN session
(savings *compound* via the swarm loop) + a **raw-vs-compressed Claude output side-by-side**
proving no quality loss. To beat API-only teams: add a thin **RETURN-specific semantic dedup**
pass before their API (collapse near-duplicate episodic facts / overlapping snapshots),
benchmarked against control — hits their "creative approaches" language.

---

## 4. REDIS — credits $50 (`CALHACKER2026`) — **prize TBC, confirm at booth**

**Status:** **No named prize/criteria announced** in #spons-redis (only credits + workshop) —
re-checked Slack 2026-06-20: Simran's kickoff post lists $50 credits, a setup slide deck, and
the workshop; a channel search for "prize"/"track"/"criteria"/"Best Use of Redis" returns
nothing. **Confirm at the booth.** $50/participant credits, code `CALHACKER2026`; free tier at
redis.io/try-free. Workshop **4–5pm, 5th Floor Tilden** (confirmed in the kickoff post). Reps:
Simran Regmi, Justin (both signed the kickoff post as "Simran and Justin from Redis").

**Architecture verdict (from `docs/raw-to-principles-research.md` §4): Redis is OUT of v1.**
The vertical (raw → memory → principles) runs on SQLite + Postgres/pgvector via Hindsight.
Redis sits off that path. Per-capability reasoning:

| Redis capability | v1 status | Why |
|---|---|---|
| Vector search | **redundant** | pgvector via Hindsight already covers it |
| Agent Memory Server | **redundant + weaker** | Hindsight types *and* synthesizes; Redis doesn't synthesize |
| Streams / consumer-group queues | **premature** | single-user volume is trivial; v1 queues are SQLite-backed |
| Graph / entity relations | **dead** | RedisGraph EOL 2025-01-31; successor FalkorDB is a separate product |
| **RedisVL `SemanticCache`** | **the only real add — if measured** | cache recall+reason on near-duplicate capsules |

**The one defensible play — `SemanticCache`, contingent on measurement.** Put it in front of
the swarm's recall so a near-duplicate capsule skips the multi-agent LLM round-trip:
```python
from redisvl.extensions.cache.llm import SemanticCache
cache = SemanticCache(name="contradiction_cache", distance_threshold=0.15, ttl=3600, redis_url=REDIS_URL)
hit = cache.check(prompt=capsule_text, num_results=1)
verdict = hit[0]["response"] if hit else run_swarm(capsule_text)
if not hit: cache.store(prompt=capsule_text, response=verdict, metadata={"principle_ids": ids})
```
Add it **only after instrumenting the repeat-query rate** — savings are workload-dependent.
Be honest about the numbers: Redis's "~68.8% fewer calls / 160×" are best-case per-request
marketing, not system-level. The honest model is **system latency ∝ hit-rate** (~25–30%
saved at a 30% hit rate). Don't quote the marketing figures on stage as if they were ours.

**Do NOT** use Redis for graph/principles — RedisGraph is **EOL**; principles stay in
Postgres+pgvector. Stating this boundary to judges signals architectural judgment.

**Win (if we touch it at all):** a measured `SemanticCache` story — instrument the repeat-query
rate first, then put a real **number** on stage (measured hit-rate → latency saved on the
swarm path). Hit the 4–5pm workshop to confirm whether a prize exists and meet Simran/Justin.

---

## 5. INTERACTION CO / POKE — **no prize (thematic), but a real, easy integration**

**Verdict:** no prize/criteria posted → no judging upside, but Poke has a **real API** and is
a drop-in delivery channel for RETURN's core nudge feature. Worth a **small time-boxed build**
(few hours) for a memorable general-judging beat; we're already in an imessage-poc worktree.

**Surface:** Poke = proactive AI assistant in iMessage/WhatsApp/Telegram (Apple-approved as
the first 3rd-party AI agent on Messages). Two integration paths:
- **SEND API (recommended):** `POST https://poke.com/api/v1/inbound/api-message`, `Authorization: Bearer <V2 key>`
  (key from poke.com/kitchen), body `{"message": "..."}` → delivered into the user's iMessage.
  ~20-line FastAPI outbound call.
- **MCP (stretch):** Poke calls *your* MCP server's tools (`list_nearby_capsules`,
  `unlock_capsule`) keyed by `X-Poke-User-Id`. Templates: github.com/InteractionCo/poke-mcp-examples.
  Open question: whether Poke calls tools proactively/on schedule — verify at booth.

Workshop Sat 2pm, Tilden Floor 5. Access: DM reps Claudia (@claudia) / Hannah (@hannah).

**Plan:** on a geofence "you've returned" event or capsule unlock, RETURN fires the SEND API
with the reflection prompt → Poke surfaces it in the user's real iMessage thread (and can
handle the reply). Demo: *"RETURN's location capsules reach you in the iMessage thread you
already live in — no new app."* Do **not** build the MCP server unless the SEND API lands
early and reps confirm proactive calls.

---

## 6. ANTHROPIC — "Best Use of Claude" — **Tungsten Cube + $5,000 API credits**

**Track confirmed (Devpost):** Claude is a *co-host*. Prize = Tungsten Cube + $5,000 API
credits (+ a related listing mentions an **Applied-AI office hour + SF office invite** —
confirm at booth). **Criteria:** (1) Technical Complexity — innovative use of Claude **Code**
beyond basics; (2) Creative Use Case — novel, beyond standard dev workflows; (3) Impact &
Practicality. Criteria reward Claude **Code** usage explicitly. Competitive — teams already
forming on "Anthropic+Sentry+Arize."

**Credits (today, in Slack):** **$25** self-serve →
`https://claude.com/offers?offer_code=fb3203ec-b5d7-48a4-ab38-5fe5d9bcd026` (near-instant).
Separate **Claude Code credits form** from Anthropic (organizer Collin H. confirmed — submit
early). `.edu` credits = larger separate program; apply from a **personal account on your
school email**, not an org-linked one (org-without-.edu-owner gets rejected). Workshop already
happened — ping channel/booth for slides. Submission deadline **6/21 11:00 AM PDT**.

**Models (exact IDs):** `claude-opus-4-8` ($5/$25 per 1M, 1M ctx) — REFLECT, Critic/Arbiter;
`claude-sonnet-4-6` ($3/$15) — high-volume extraction/NLI; `claude-haiku-4-5` ($1/$5) — cheap
classify/retriever pre-filter. On Opus 4.8, `temperature`/`top_p`/`budget_tokens` are removed
→ use `thinking:{type:"adaptive"}` + `output_config:{effort:"high"}`.

**Integration (the cost-engineering *is* the story):**
- **REFLECT → Opus 4.8 + adaptive thinking + prompt caching.** The 4-network memory context
  is a large stable prefix re-sent every call → put it first with
  `cache_control:{type:"ephemeral"}` (cache reads ~0.1× input). This is what makes repeated
  synthesis affordable on $25. Volatile capsule/question goes *after* the breakpoint.
- **Swarm → manual tool-use loop + structured outputs.** Critic/Arbiter return typed
  `{contradicts, principle_id, confidence, evidence}` via `json_schema` → deterministic
  flywheel, no regex. Retriever on Haiku/Sonnet pre-filters.
- **Passive ingestion → Batch API (50% cheaper)** on Sonnet/Haiku for the non-latency-
  sensitive chat.db backfill, typed Events via json_schema.
- **"Talk to past you" → prompt caching per temporal snapshot** (snapshot = cached prefix).

**Win:** demo a live REFLECT surfacing a cross-memory principle the user never stated (hits
Creative + Technical at once); show the contradiction flywheel sharpening a principle; **name
the Claude features** in the pitch (caching the principle graph, adaptive thinking, structured-
output routing, Batch ingestion); **build with Claude Code and say so.** Cross-check the exact
RETURN model strategy against the `claude-api` skill before quoting prices.

---

## 7. DEEPGRAM — voice experience — **Nintendo Switch 2**

**Prize + criteria (confirmed, Naomi Carrigan, Deepgram):** Switch 2 for the "most creative &
well-executed voice-powered experience." Must use ≥1 Deepgram voice product (STT/TTS/Voice
Agent) as the **CORE** experience, *"not just an afterthought."* Judged on 3 axes: (1) how
**creative** the voice component is; (2) how **fundamental** voice is; (3) technical execution.

**Offer:** $200 credits via event link **https://dpgr.am/ucb-ai-signup** (plenty — Nova-3 STT
$0.0048/min, Aura-2 TTS $0.030/1k chars, Voice Agent $0.075/min). Docs dpgr.am/ucb-ai-docs;
Discord dpgr.am/ubc-ai-discord. **Workshop Sat 2–3pm** builds exactly our hero pipeline
(STT→LLM→TTS on one WebSocket) — go. Mentor: Naomi Carrigan (@naomi.carrigan). `pip install deepgram-sdk`.

**Integration (voice as core):**
- **Nova-3 STT** → spoken capsules/journal entries feed Hindsight (voice as an ingestion primitive).
- **Aura-2 TTS** → *voice* your past self; distinct voice per temporal snapshot (older = warmer/slower).
- **Voice Agent API (Flux + LLM + Aura-2, one WebSocket)** → the "talk to past you" loop; the
  `think.prompt` is built from the principle-graph snapshot at that timestamp (≤25k chars).
  Note: Flux requires `version:"v2"`, no `smart_format`; set `eager_eot_threshold ≤ eot_threshold`.
- **Audio Intelligence** (sentiment/topics/intents, same `/listen` call) → mood tag (-1..1) on
  the memory, auto-category, intents feeding REFLECT.

**Win — the beat:** on stage, speak a new capsule (live transcribe + sentiment), open the
past-self persona pinned to an earlier snapshot, ask it aloud "was I happy back then?" → it
answers **in a voice**, reasoning only from that snapshot, audibly not knowing what came
later. Nails all 3 axes (typing can't "talk to past you" → voice is fundamental).

---

## 8. ELEVENLABS — **no track posted yet (booth) — but our STRONGEST voice fit**

**Status:** re-checked Slack — **still no rep, offer, or prize posted** (only hackers asking
for credits). **Booth is the source of truth**; they hand out Creator-tier codes physically
and any track ("best use of ElevenLabs / Conversational AI") gets announced there.

**Why it beats Deepgram for RETURN:** **voice cloning** (IVC: clone from <2 min audio, **free
tier = 3 slots**) → the past self speaks in the user's *own* cloned voice. Deepgram's Aura
cannot clone arbitrary voices, so the emotional hero beat is **only possible on ElevenLabs.**
Also leads on emotive TTS and a richer agent platform (ElevenAgents: builder + client tools +
MCP). Deepgram still wins on raw STT cost/latency.

**Product:** TTS `eleven_multilingual_v2` (emotive narration), `eleven_flash_v2_5` (~75ms,
half-price, real-time); STT **Scribe v2** (`scribe_v1` removed Jul 9 2026 — don't use);
ElevenAgents conversational platform (BYO Claude LLM). Free tier 10k credits/mo + 3 IVC slots,
**no commercial license** (fine for demo). `pip install elevenlabs`.

**Integration:** clone **per temporal snapshot** (`past-self-2024` vs `-2026`) via
`client.voices.ivc.create(files=[...voice notes...])`; narrate capsules with TTS stream;
run the reflection loop as a Conversational Agent voiced with the clone, injecting the
snapshot graph as a **client tool** (`recall_snapshot`) so it answers as the past you. Frontend
`@elevenlabs/react` for mic-in/audio-out; agent config + graph tool server-side in FastAPI;
agent LLM = Claude.

**Win:** judge presses play → hears a past version of the user speaking in the user's **own
voice**, then a live spoken back-and-forth grounded in real snapshot data. To win *their*
prize keep it end-to-end on ElevenLabs (Scribe v2 Realtime for STT). If no track materializes,
this still powers the grand-prize hero demo.

---

## 9. FETCH.AI — "Best Use of Agentverse" — **$1,500 / $1,000 / $500 + interviews** (stackable, mandatory)

**Prize/criteria (fetch.ai event page + hackpack):** $3,000 pool (1st $1.5k / 2nd $1k / 3rd
$500), each + internship interview. Rubric: Functionality 25% · **Use of Fetch.ai Tech 20%** ·
Innovation 20% · Real-World Impact 20% · UX/Presentation 15%. **Using the product is
MANDATORY** — agents registered on Agentverse + **Chat Protocol** (mandatory), core must work
through **ASI:One** (no custom frontend required). **Stackable with a Ddoski grand prize
(confirmed in Slack).**

**Access:** promo `BERKELEYAIAV` → 1mo ASI:One Pro + Agentverse Premium. `pip install uagents`;
helper `npx create-fetch-agent`. ASI:One API `https://api.asi1.ai/v1` (model `asi1`), keys at
asi1.ai/dashboard/api-keys. Heavy mentor presence in #cohost-fetch-ai (RV, Gautam, Dev
Chauhan…); live workshop 5th Floor Tilden; demo target https://chat.asi1.ai/.

**Integration (thin, stackable):** wrap RETURN's memory as **one discoverable "RETURN Memory
Agent"** uAgent — its `ChatMessage` handler calls our existing principle-graph/swarm logic.
MVP ≈ 1 file: register with `mailbox=True, publish_agent_details=True`, include a
`Protocol(spec=chat_protocol_spec)`, `agent.include(proto, publish_manifest=True)` → auto-
discoverable on ASI:One. Add good keywords + README on Agentverse (affects routing). Stretch:
expose Retriever/Critic/Arbiter as agents that talk to each other (scores Functionality).

**Win:** clear the mandatory bar cleanly (live ASI:One demo, no frontend needed); lean on our
**existing swarm** as the differentiator (near-free); write strong keywords/README; get a
mentor's eyes on it at the Tilden workshop. ~1 evening for the MVP wrapper.

---

## 10. SIMULAR (Sai / SimuLang) — "#SaiCal" — **$500/person** ($100 GC + $400 credits)

**Prize/criteria (Slack, Zening Chen):** $500/person on winning team. Judged on creativity
(bonus for novel use) + technical execution + real-world impact; **must meaningfully use Sai
OR SimuLang.** Eligibility chores: every teammate follows Sai (X/IG/LinkedIn), post with
**#SaiCal** tagging Sai, email screenshots to **zening@simular.ai**. (Precedent: Agent S
powered last year's 1st-place winner.)

**Access:** 2-day unlimited-credit trial gated by an **invite code** — capacity-limited, get
one **in person** (booth 3rd floor by entrance, or the workshop). **Blocker:** without a code,
Sai login only offers "Founder plan" — grab a code ASAP. Workshop 12–1pm Floor 2; headline
demo is literally *"orchestrate Claude Code in iMessage"* — our territory.

**What they are:** **Sai** = hosted computer-use agent (remote desktop is **Windows**).
**SimuLang** = OSS "Playwright for the desktop" (TS, drives apps via accessibility tree);
installs as a **Claude Code skill** (`simulang init-claude` → `/simulang <task>`).

**Integration (lead with SimuLang):**
- **SimuLang = RETURN's universal cross-app ingestion layer.** chat.db stays the fast path for
  iMessage; SimuLang covers apps with no clean export (Notes, Photos captions, web apps) by
  driving the GUI and POSTing to our FastAPI `/ingest`. Generate each extractor live via
  `/simulang`. Makes "passive ingestion across apps" real.
- **Sai orchestrates RETURN over iMessage** (mirrors their headline demo): text a location →
  Sai triggers ingest/query → Claude composes the capsule → texted back.
- **Caveat:** Sai's desktop is Windows → chat.db/macOS SimuLang work runs as a **local daemon
  on our Mac**; use Sai for the iMessage-orchestration + demo-video layer. Don't promise Sai
  reading chat.db.

**Win:** demo `/simulang` writing a **brand-new extractor live** for an app you've never seen
(a judge's Notes / a web app) → memory appears location-tagged seconds later. Use Sai's
one-prompt video feature for the submission (dogfooding scores). Don't fluff the follow/
#SaiCal/email logistics.

---

## Action items (tonight / Hour-0)

**Pick the lane:** Ddoski's World (grand) + **Anthropic** (core) are non-negotiable. Then the
near-free observability stack (Arize + Sentry), then Token Co. **One voice decision:**
ElevenLabs-led (cloning hero beat) vs Deepgram-led — don't split effort.

- [ ] **Submit to Ddoski's World** on Devpost; confirm overall criteria.
- [ ] **Anthropic:** redeem $25 link + submit the Claude Code credits form; build with Claude Code; add prompt caching over the 4-network context + structured-output contradiction routing. (cross-check models via `claude-api` skill)
- [ ] **Token Company:** grab `ttc-` key, wrap REFLECT with `compress()`, instrument cumulative `tokens_saved`; open the login-gated criteria doc signed-in.
- [ ] **Fetch.ai:** apply promo `BERKELEYAIAV`; ship the 1-file RETURN Memory uAgent on ASI:One (mandatory if chasing this prize).
- [ ] **Arize:** sign up app.arize.com, add tracing import, build a groundedness evaluator, capture before/after. (booth-judged — highest-confidence $1k)
- [ ] **Sentry:** free sentry.io account, 3 init blocks, `gen_ai.*` spans, `tracePropagationTargets`; rehearse click→trace→failure→Seer.
- [ ] **Voice (pick one):** ElevenLabs — grab booth code, clone past-self from voice notes (IVC, 3 free slots); **or** Deepgram — $200 via dpgr.am/ucb-ai-signup, attend 2–3pm workshop.
- [ ] **Redis (out of v1):** attend 4–5pm Tilden workshop, **confirm whether a prize exists**. Only add `SemanticCache` if we first measure a repeat-query rate that justifies it — skip queues/vector/graph (redundant or premature).
- [ ] **Simular (optional):** grab an invite code in person, `/simulang` a new extractor for the demo; do the #SaiCal follow/post/email chores.
- [ ] **Poke (optional):** V2 key from Claudia/Hannah, one SEND-API POST for the iMessage nudge demo.

**Human-needed verifications:** Redis prize criteria (booth), Token Co criteria doc (login),
ElevenLabs track (booth), Anthropic office-hour detail (booth), Fetch hackpack exact weights (login).
