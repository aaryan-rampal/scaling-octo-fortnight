/* RETURN — frontend controller.
 * Drives the loop over SEED (seed.js): capsules → (return/unlock) → reconstruct
 * → reveal → talk to past you. All data access goes through getPlaces()/getPlace()
 * so swapping in a real backend is a one-function change.
 */

// --- data access (swap these two for fetch() when the backend is live) ---
const getPlaces = () => SEED.places;
const getPlace = (id) => SEED.places.find((p) => p.id === id);

// honor the OS "reduce motion" setting (a11y — ui-ux-pro-max §7)
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// capsules the user has "returned" to this session (location-lock stand-in)
const unlocked = new Set(getPlaces().filter((p) => !p.sealed).map((p) => p.id));
const isLocked = (p) => p.sealed && !unlocked.has(p.id);

// --- inline icons (SVG, never emoji) ---
const ICON = {
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="11" width="17" height="10" rx="2"/><path d="M7.5 11V7a4.5 4.5 0 0 1 9 0v4"/></svg>',
  unlocked: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="11" width="17" height="10" rx="2"/><path d="M7.5 11V7a4.5 4.5 0 0 1 8.9-1"/></svg>',
  compass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z"/></svg>',
};

// --- view routing ---
const views = {
  places: document.getElementById("view-places"),
  reconstruct: document.getElementById("view-reconstruct"),
  reveal: document.getElementById("view-reveal"),
};
function show(name) {
  Object.values(views).forEach((v) => v.classList.remove("active"));
  views[name].classList.add("active");
  document.querySelector(".screen").scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
}

let active = null;

// --- 1. capsules ---
function renderPlaces() {
  const list = document.getElementById("place-list");
  list.innerHTML = "";
  getPlaces().forEach((p) => {
    const locked = isLocked(p);
    const el = document.createElement("article");
    el.className = "place";
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", locked ? `Sealed capsule at ${p.name} — return to open` : `Open capsule at ${p.name}`);
    el.innerHTML = `
      <div class="place-cover" style="background:${p.cover}"></div>
      <div class="place-scrim"></div>
      <div class="place-glyph">${p.icon}</div>
      <div class="place-top">
        <span class="place-loc">${ICON.pin}${p.place}</span>
        <span class="place-badge ${locked ? "sealed" : "open"}">
          ${locked ? ICON.lock + "Sealed" : ICON.unlocked + "Open"}
        </span>
      </div>
      <div class="place-body">
        <h3 class="pname">${p.name}</h3>
        <div class="pmeta"><span class="mood-dot" style="--h:${p.mood.hue}"></span>${p.mood.label} · ${p.visits}</div>
      </div>
      ${locked ? `<button class="imback">I'm back ↩</button>` : ``}`;
    const go = () => activate(p);
    el.addEventListener("click", go);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
    list.appendChild(el);
  });
}

// returning unlocks a sealed capsule, then opens it
function activate(p) {
  if (isLocked(p)) { unlocked.add(p.id); renderPlaces(); }
  openPlace(p.id);
}

const moodPill = (m) => `<span class="mood-pill" style="--h:${m.hue}">${m.label}</span>`;

// --- 2. reconstruct-before-reveal ---
function openPlace(id) {
  active = getPlace(id);
  const a = active.anchor;
  document.getElementById("anchor-photo").style.background = a.photo;
  document.getElementById("anchor-place").textContent = a.place;
  document.getElementById("anchor-time").textContent = a.time;
  document.getElementById("anchor-mood").outerHTML =
    `<span id="anchor-mood" class="mood-pill" style="--h:${active.mood.hue}">${active.mood.label}</span>`;

  const feed = document.getElementById("reconstruct-feed");
  feed.innerHTML = "";
  const revealBtn = document.getElementById("reveal-btn");
  revealBtn.classList.add("hidden");
  show("reconstruct");

  const cueHTML = (c) => `
    <div class="ctype">${c.type}</div>
    <div class="ctext">${c.text}</div>
    <div class="ctime">${c.time}</div>`;

  if (reduceMotion) {
    active.cues.forEach((c) => {
      const el = document.createElement("div");
      el.className = "cue";
      el.style.opacity = "1";
      el.innerHTML = cueHTML(c);
      feed.appendChild(el);
    });
    revealBtn.classList.remove("hidden");
    return;
  }

  active.cues.forEach((c, i) => {
    setTimeout(() => {
      const el = document.createElement("div");
      el.className = "cue";
      el.innerHTML = cueHTML(c);
      feed.appendChild(el);
      if (i === active.cues.length - 1) {
        setTimeout(() => revealBtn.classList.remove("hidden"), 400);
      }
    }, 650 * (i + 1));
  });
}

document.getElementById("reveal-btn").addEventListener("click", reveal);

// --- 3. grounded storyline + reflection + talk-to-past-you ---
function reveal() {
  const storyEl = document.getElementById("storyline");
  let html = active.storyline.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  html = html.replace(/\{(\d+)\}/g, (_, i) => {
    const cite = active.citations[Number(i)];
    return `<sup class="cited" title="${cite ? cite.label : ""}">[${cite ? cite.n : "?"}]</sup>`;
  });
  storyEl.innerHTML = html;

  document.getElementById("citations").innerHTML = active.citations
    .map((c) => `<span class="chip"><b>[${c.n}]</b> ${c.label}</span>`)
    .join("");

  document.getElementById("principle").innerHTML =
    `<span class="plabel">Principle</span><span class="ptext">“${active.principle}”</span>`;

  // forward-looking reflection — never "go back to how it was" (wellbeing guardrail)
  document.getElementById("reflection").innerHTML =
    `<div class="rlabel">${ICON.compass} Carry forward</div><div class="rtext">${active.reflection}</div>`;

  document.getElementById("seal-date").textContent = active.sealDate;

  const chat = document.getElementById("chat");
  chat.innerHTML = "";
  addBubble("past", active.opener);

  show("reveal");
}

// --- persona chat (rule-based stand-in for seal-time-conditioned LLM) ---
function addBubble(who, text) {
  const chat = document.getElementById("chat");
  const el = document.createElement("div");
  el.className = `bubble ${who}`;
  el.innerHTML = who === "past" ? `<span class="who">past you</span>${text}` : text;
  chat.appendChild(el);
  el.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
}

function pastReply(q) {
  const text = q.toLowerCase();
  const hit = active.replies.find((r) => r.match.some((m) => text.includes(m)));
  return hit ? hit.text : active.fallback;
}

document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const q = input.value.trim();
  if (!q) return;
  addBubble("you", q);
  input.value = "";
  setTimeout(() => addBubble("past", pastReply(q)), 550);
});

// --- back navigation ---
document.querySelector("[data-back]").addEventListener("click", () => show("places"));
document.querySelector("[data-back-reconstruct]").addEventListener("click", () => show("reconstruct"));

// --- boot ---
renderPlaces();
show("places");
