/* RETURN — frontend controller.
 * Loop: MAP (explore) → visit a fogged spot to discover it → seal a capsule
 * (or open one) → reconstruct → reveal → talk to past you.
 * All data access goes through getPlaces()/getPlace() so a real backend is a
 * one-function swap. Visual language follows ui-ux-pro-max "Modern Dark
 * (Cinema Mobile)": frosted nav, ambient glow, Expo.out easing, 0.97 press.
 */

const getPlaces = () => SEED.places;
const getPlace = (id) => SEED.places.find((p) => p.id === id);
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// runtime state
const discovered = new Set(SEED.map.filter((m) => m.discovered).map((m) => m.id));
const unlocked = new Set(getPlaces().filter((p) => !p.sealed).map((p) => p.id));
const isDiscovered = (poi) => discovered.has(poi.id);
const isLocked = (p) => p.sealed && !unlocked.has(p.id);

// --- inline icons (SVG, never emoji) ---
const ICON = {
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="11" width="17" height="10" rx="2"/><path d="M7.5 11V7a4.5 4.5 0 0 1 9 0v4"/></svg>',
  unlocked: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="11" width="17" height="10" rx="2"/><path d="M7.5 11V7a4.5 4.5 0 0 1 8.9-1"/></svg>',
  compass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
  capsule: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>',
};

const escapeHTML = (s) => s.replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// --- sound (synthesized, no asset files; runs on user gesture) ---
const SoundFX = (() => {
  let ctx;
  const ac = () => {
    if (!ctx) { const C = window.AudioContext || window.webkitAudioContext; if (C) ctx = new C(); }
    if (ctx && ctx.state === "suspended") ctx.resume();
    return ctx;
  };
  const tone = (freq, t0, dur, type = "sine", gain = 0.18) => {
    const c = ac(); if (!c) return;
    const o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.value = freq; o.connect(g); g.connect(c.destination);
    const t = c.currentTime + t0;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.start(t); o.stop(t + dur + 0.03);
  };
  return {
    discover() { try { tone(392, 0, .12, "triangle", .16); tone(587, .09, .2, "triangle", .14); } catch {} },
    dig() { try { tone(120, 0, .14, "sine", .28); tone(90, .13, .16, "sine", .22); tone(150, .26, .1, "sine", .15); } catch {} },
    unlock() { try { tone(523, 0, .1, "sine", .16); tone(659, .08, .1, "sine", .16); tone(784, .16, .22, "sine", .18); } catch {} },
    open() { try { tone(659, 0, .2, "sine", .2); tone(988, .1, .3, "sine", .17); tone(1319, .22, .45, "sine", .12); } catch {} },
    shimmer() { try { tone(880, 0, .28, "sine", .12); tone(1175, .07, .32, "sine", .1); tone(1568, .15, .3, "sine", .07); } catch {} },
  };
})();

// pins highlighted by a principle "trace"
const highlight = new Set();
let highlightTimer;

// --- view routing ---
const views = {
  map: document.getElementById("view-map"),
  places: document.getElementById("view-places"),
  create: document.getElementById("view-create"),
  reconstruct: document.getElementById("view-reconstruct"),
  reveal: document.getElementById("view-reveal"),
};
const FLOW = ["create", "reconstruct", "reveal"]; // hide tab bar in these
function show(name) {
  Object.values(views).forEach((v) => v.classList.remove("active"));
  views[name].classList.add("active");
  document.getElementById("tabbar").classList.toggle("hidden", FLOW.includes(name));
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active",
      (name === "map" && t.dataset.tab === "map") ||
      (name === "places" && t.dataset.tab === "capsules")));
  document.querySelector(".screen").scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
}
const switchTab = (tab) => show(tab === "map" ? "map" : "places");

let active = null;

// --- toast ---
let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

// --- 1. MAP ---
function renderMap() {
  const pins = document.getElementById("map-pins");
  pins.innerHTML = "";
  let found = 0;

  SEED.map.forEach((poi) => {
    const disc = isDiscovered(poi);
    if (disc) found++;
    const cap = poi.capsuleId ? getPlace(poi.capsuleId) : null;

    const btn = document.createElement("button");
    btn.className = "pin";
    btn.style.left = poi.x + "%";
    btn.style.top = poi.y + "%";

    let inner, label;
    if (!disc) {
      btn.classList.add("fog");
      btn.setAttribute("aria-label", "Undiscovered location — visit to reveal");
      inner = "?"; label = "? ? ?";
    } else if (cap) {
      btn.classList.add("cap");
      const locked = isLocked(cap);
      if (locked) btn.classList.add("sealed");
      btn.setAttribute("aria-label", `${locked ? "Sealed" : "Open"} capsule at ${poi.name}`);
      inner = cap.icon + (locked ? `<span class="lockbadge">${ICON.lock}</span>` : "");
      label = poi.name;
    } else {
      btn.classList.add("empty");
      btn.setAttribute("aria-label", `Seal a capsule at ${poi.name}`);
      inner = ICON.plus; label = poi.name;
    }
    btn.innerHTML = `<span class="pin-marker">${inner}</span><span class="pin-label">${label}</span>`;
    if (poi._justRevealed) { btn.classList.add("just-revealed"); delete poi._justRevealed; }
    if (highlight.has(poi.id)) btn.classList.add("highlight");

    btn.addEventListener("click", () => onPoiClick(poi));
    btn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPoiClick(poi); }
    });
    pins.appendChild(btn);
  });

  const player = document.createElement("div");
  player.className = "player";
  player.style.left = "38%";
  player.style.top = "89%";
  player.innerHTML = `<div class="player-dot"></div><div class="player-label">you</div>`;
  pins.appendChild(player);

  document.getElementById("map-progress").textContent = `${found}/${SEED.map.length} discovered`;
}

function onPoiClick(poi) {
  if (!isDiscovered(poi)) { visit(poi); return; }
  const cap = poi.capsuleId ? getPlace(poi.capsuleId) : null;
  if (cap) openCapsule(cap);
  else startCreate(poi);
}

function visit(poi) {
  discovered.add(poi.id);
  poi._justRevealed = true;
  SoundFX.discover();
  renderMap();
  toast(poi.capsuleId ? `Back at ${poi.name}` : `Discovered ${poi.name} — seal a memory here`);
}

// --- 2. CREATE a capsule ---
let createPoi = null, selMood = null, selCover = null;
function startCreate(poi) {
  createPoi = poi;
  selMood = SEED.moods[0];
  selCover = SEED.covers[0];
  document.getElementById("create-loc-icon").innerHTML = ICON.pin;
  document.getElementById("create-place").textContent = poi.name;
  document.getElementById("mood-row").innerHTML = SEED.moods
    .map((m, i) => `<button type="button" class="mchip${i ? "" : " sel"}" style="--h:${m.hue}" data-i="${i}">${m.label}</button>`)
    .join("");
  document.getElementById("cover-row").innerHTML = SEED.covers
    .map((c, i) => `<button type="button" class="cover-sw${i ? "" : " sel"}" style="background:${c}" data-i="${i}" aria-label="Cover ${i + 1}"></button>`)
    .join("");
  document.getElementById("create-note").value = "";
  show("create");
}

document.getElementById("mood-row").addEventListener("click", (e) => {
  const b = e.target.closest(".mchip"); if (!b) return;
  selMood = SEED.moods[+b.dataset.i];
  [...e.currentTarget.children].forEach((c) => c.classList.remove("sel"));
  b.classList.add("sel");
});
document.getElementById("cover-row").addEventListener("click", (e) => {
  const b = e.target.closest(".cover-sw"); if (!b) return;
  selCover = SEED.covers[+b.dataset.i];
  [...e.currentTarget.children].forEach((c) => c.classList.remove("sel"));
  b.classList.add("sel");
});

document.getElementById("create-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const note = document.getElementById("create-note").value.trim() || "No words — just being here.";
  const id = "c" + Date.now();
  const cap = {
    id, icon: ICON.capsule, name: createPoi.name, place: createPoi.name,
    visits: "just sealed", sealed: true, mood: selMood, cover: selCover,
    storyline: escapeHTML(note),
    citations: [], principle: "",
    reflection: "When you open this, what will you want to remember about who you are today?",
    sealDate: "sealed just now",
    opener: "what were you hoping for when you sealed this?",
    replies: [], fallback: "I sealed this moment for you — that's all I know yet.",
    anchor: { place: createPoi.name, time: "just now", photo: selCover },
    userCreated: true,
  };
  SEED.places.push(cap);
  createPoi.capsuleId = id;
  discovered.add(createPoi.id);
  createPoi._justRevealed = true;
  renderMap();
  renderPlaces();
  switchTab("map");
  toast(`Sealed at ${cap.name}. Come back to open it.`);
});

// --- 3. CAPSULES tab ---
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
    const go = () => openCapsule(p);
    el.addEventListener("click", go);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
    list.appendChild(el);
  });
}

// open a capsule — big unearth/open animation (~80% screen) + sound, then the
// same reveal page you'd see right after finishing/sealing it.
function openCapsule(cap) {
  const wasLocked = isLocked(cap);
  if (wasLocked) {
    unlocked.add(cap.id);
    renderMap();
    renderPlaces();
  }
  active = cap;
  const proceed = () => { if (cap.cues && cap.cues.length) openPlace(cap.id); else reveal(); };
  openingSequence(wasLocked, proceed);
}

// the big capsule graphic + dig/open sound, then the page
function openingSequence(wasLocked, after) {
  const ov = document.getElementById("opening");
  document.getElementById("opening-text").textContent = wasLocked ? "unearthing…" : "opening…";

  if (reduceMotion) { SoundFX.open(); after(); return; }

  ov.classList.add("show");
  // restart the CSS animations
  ov.querySelectorAll(".opening-cap-icon, .opening-glow, .dust").forEach((el) => {
    el.style.animation = "none"; void el.offsetWidth; el.style.animation = "";
  });
  if (wasLocked) { SoundFX.dig(); setTimeout(() => SoundFX.unlock(), 360); setTimeout(() => SoundFX.open(), 760); }
  else { SoundFX.dig(); setTimeout(() => SoundFX.open(), 380); }

  setTimeout(() => { ov.classList.remove("show"); after(); }, 1250);
}

// principle → light up the capsule(s) it was formed from, on the map
function tracePrinciple(cap) {
  const ids = SEED.map
    .filter((poi) => poi.capsuleId && getPlace(poi.capsuleId) &&
      getPlace(poi.capsuleId).principle === cap.principle)
    .map((poi) => poi.id);
  if (!ids.length && cap.mapId) ids.push(cap.mapId);
  highlight.clear();
  ids.forEach((id) => highlight.add(id));
  switchTab("map");
  renderMap();
  SoundFX.shimmer();
  const names = SEED.map.filter((p) => ids.includes(p.id)).map((p) => p.name).join(", ");
  toast(`This principle was formed at: ${names || cap.name}`);
  clearTimeout(highlightTimer);
  highlightTimer = setTimeout(() => { highlight.clear(); renderMap(); }, 4000);
}

// --- reconstruct-before-reveal (seeded memories) ---
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
      el.className = "cue"; el.style.opacity = "1";
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
      if (i === active.cues.length - 1) setTimeout(() => revealBtn.classList.remove("hidden"), 400);
    }, 650 * (i + 1));
  });
}

document.getElementById("reveal-btn").addEventListener("click", reveal);

// --- grounded storyline + reflection + talk-to-past-you ---
function reveal() {
  document.querySelector("#view-reveal .section-label").textContent =
    active.userCreated ? "Your note, sealed" : "The night, reconstructed";

  const html = active.storyline.replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\{(\d+)\}/g, (_, i) => {
      const cite = (active.citations || [])[Number(i)];
      return `<sup class="cited" title="${cite ? cite.label : ""}">[${cite ? cite.n : "?"}]</sup>`;
    });
  document.getElementById("storyline").innerHTML = html;

  const cites = active.citations || [];
  const citeEl = document.getElementById("citations");
  citeEl.style.display = cites.length ? "" : "none";
  citeEl.innerHTML = cites.map((c) => `<span class="chip"><b>[${c.n}]</b> ${c.label}</span>`).join("");

  const prinEl = document.getElementById("principle");
  if (active.principle) {
    const cap = active;
    prinEl.style.display = "";
    prinEl.classList.add("clickable");
    prinEl.innerHTML = `<span class="plabel">Principle</span><span class="ptext">“${active.principle}”</span><span class="ptrace">tap to light up where this came from →</span>`;
    prinEl.onclick = () => tracePrinciple(cap);
  } else {
    prinEl.style.display = "none";
    prinEl.classList.remove("clickable");
    prinEl.onclick = null;
  }

  // forward-looking reflection — never "go back to how it was" (wellbeing guardrail)
  document.getElementById("reflection").innerHTML =
    `<div class="rlabel">${ICON.compass} Carry forward</div><div class="rtext">${active.reflection}</div>`;

  document.getElementById("seal-date").textContent = active.sealDate;

  document.getElementById("chat").innerHTML = "";
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
  const hit = (active.replies || []).find((r) => r.match.some((m) => text.includes(m)));
  return hit ? hit.text : active.fallback;
}
document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const q = input.value.trim();
  if (!q) return;
  addBubble("you", escapeHTML(q));
  input.value = "";
  setTimeout(() => addBubble("past", pastReply(q)), 550);
});

// --- tabs + back nav ---
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
document.querySelectorAll("[data-back-map]").forEach((b) => b.addEventListener("click", () => show("map")));

// --- boot ---
renderMap();
renderPlaces();
show("map");
