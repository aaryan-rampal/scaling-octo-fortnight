/* RETURN — frontend controller.
 * Loop: HOME → DISCOVER → (dig old: places / drop new: camera → drag → create)
 *        HOME → MAP → open capsule → reconstruct → reveal → talk to past you
 *        MAP → compass → PRINCIPLES MAP
 * All data access goes through getPlaces()/getPlace() so a real backend is a
 * one-function swap.
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
    tap() { try { tone(440, 0, .08, "sine", .1); } catch {} },
  };
})();

// pins highlighted by a principle "trace"
const highlight = new Set();
let highlightTimer;

// --- view routing ---
const views = {
  home: document.getElementById("view-home"),
  discover: document.getElementById("view-discover"),
  map: document.getElementById("view-map"),
  graph: document.getElementById("view-graph"),
  places: document.getElementById("view-places"),
  create: document.getElementById("view-create"),
  reconstruct: document.getElementById("view-reconstruct"),
  reveal: document.getElementById("view-reveal"),
  camera: document.getElementById("view-camera"),
  drag: document.getElementById("view-drag"),
};

// hide tab bar in these flow views
const FLOW = ["create", "reconstruct", "reveal", "camera", "drag", "discover"];
const TAB_FOR_VIEW = { map: "map", graph: "graph", places: "capsules" };

function show(name) {
  Object.values(views).forEach((v) => v.classList.remove("active"));
  views[name].classList.add("active");
  const hideTab = FLOW.includes(name) || name === "home";
  document.getElementById("tabbar").classList.toggle("hidden", hideTab);
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", TAB_FOR_VIEW[name] === t.dataset.tab));
  document.querySelector(".screen").scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
}
const switchTab = (tab) => show(tab === "capsules" ? "places" : tab);

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

// --- 1. ILLUSTRATED SVG MAP ---
let svgVB = { x: 0, y: 0, w: 360, h: 400 };

function latLngToXY(lat, lng) {
  return {
    x: (lng - (-122.263)) / 0.011 * 360,
    y: (37.876 - lat) / 0.012 * 400,
  };
}

function setVB() {
  const svg = document.getElementById("map-svg");
  if (svg) svg.setAttribute("viewBox", `${svgVB.x} ${svgVB.y} ${svgVB.w} ${svgVB.h}`);
}

function initMapPanZoom() {
  const svg = document.getElementById("map-svg");
  if (!svg || svg._pzInited) return;
  svg._pzInited = true;
  let dragging = false, lx = 0, ly = 0, ld = 0;
  const MIN_W = 80, MAX_W = 720;

  svg.addEventListener("mousedown", (e) => { dragging = true; lx = e.clientX; ly = e.clientY; svg.style.cursor = "grabbing"; });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const sx = svg.clientWidth, sy = svg.clientHeight;
    svgVB.x -= (e.clientX - lx) / sx * svgVB.w;
    svgVB.y -= (e.clientY - ly) / sy * svgVB.h;
    lx = e.clientX; ly = e.clientY;
    setVB();
  });
  document.addEventListener("mouseup", () => { dragging = false; svg.style.cursor = ""; });

  svg.addEventListener("touchstart", (e) => {
    if (e.touches.length === 1) { dragging = true; lx = e.touches[0].clientX; ly = e.touches[0].clientY; }
    else if (e.touches.length === 2) { ld = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); }
  }, { passive: true });
  svg.addEventListener("touchmove", (e) => {
    if (e.touches.length === 1 && dragging) {
      const sx = svg.clientWidth, sy = svg.clientHeight;
      svgVB.x -= (e.touches[0].clientX - lx) / sx * svgVB.w;
      svgVB.y -= (e.touches[0].clientY - ly) / sy * svgVB.h;
      lx = e.touches[0].clientX; ly = e.touches[0].clientY;
      setVB();
    } else if (e.touches.length === 2) {
      const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
      const scale = ld / d;
      const cx = svgVB.w * 0.5 + svgVB.x, cy = svgVB.h * 0.5 + svgVB.y;
      const nw = Math.max(MIN_W, Math.min(MAX_W, svgVB.w * scale));
      const nh = nw * (400 / 360);
      svgVB.x = cx - nw / 2; svgVB.y = cy - nh / 2; svgVB.w = nw; svgVB.h = nh;
      ld = d;
      setVB();
    }
  }, { passive: true });
  svg.addEventListener("touchend", () => { dragging = false; });

  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const scale = e.deltaY > 0 ? 1.12 : 0.9;
    const rect = svg.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width * svgVB.w + svgVB.x;
    const py = (e.clientY - rect.top) / rect.height * svgVB.h + svgVB.y;
    const nw = Math.max(MIN_W, Math.min(MAX_W, svgVB.w * scale));
    const nh = nw * (400 / 360);
    svgVB.x = px - (px - svgVB.x) * (nw / svgVB.w);
    svgVB.y = py - (py - svgVB.y) * (nh / svgVB.h);
    svgVB.w = nw; svgVB.h = nh;
    setVB();
  }, { passive: false });
}

function ensureMap() {
  const svg = document.getElementById("map-svg");
  if (!svg) return;
  initMapPanZoom();
}

function drawMarkers() {
  const group = document.getElementById("map-markers");
  if (!group) return;
  group.innerHTML = "";
  let found = 0;
  SEED.map.forEach((poi) => {
    const disc = isDiscovered(poi);
    if (disc) found++;
    const cap = poi.capsuleId ? getPlace(poi.capsuleId) : null;
    const locked = cap && isLocked(cap);
    const { x, y } = latLngToXY(poi.lat, poi.lng);
    const shortName = poi.name.split(" ").slice(0, 2).join(" ");

    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", `map-poi ${disc ? (cap ? (locked ? "cap sealed" : "cap open") : "empty") : "fog"}`);
    g.setAttribute("transform", `translate(${x.toFixed(1)}, ${y.toFixed(1)})`);
    g.setAttribute("data-id", poi.id);

    if (!disc) {
      g.innerHTML = `
        <circle cx="0" cy="0" r="14" fill="rgba(154,120,96,0.3)" stroke="#7a6050" stroke-width="1.5" stroke-dasharray="3 2"/>
        <text y="5" text-anchor="middle" font-family="Caveat,cursive" font-size="15" fill="#9a7860" opacity=".7">?</text>`;
    } else if (cap) {
      const fillColor = locked ? "#d4aa3a" : "#edd878";
      g.innerHTML = `
        <circle class="poi-ring" cx="0" cy="0" r="22" fill="none" stroke="${locked ? "#9a7860" : "#c8902a"}" stroke-width="1.5" style="animation-delay:${Math.random() * 2}s"/>
        <g transform="rotate(-12)">
          <rect x="-15" y="-7" width="30" height="14" rx="7" fill="${fillColor}" stroke="#2a1c08" stroke-width="1.8"/>
          <ellipse cx="-15" cy="0" rx="7" ry="9" fill="${locked ? "#b08020" : "#d4aa3a"}" stroke="#2a1c08" stroke-width="1.8"/>
          <ellipse cx="15" cy="0" rx="7" ry="9" fill="${locked ? "#b08020" : "#d4aa3a"}" stroke="#2a1c08" stroke-width="1.8"/>
          <rect x="-4" y="-8" width="3.5" height="16" rx="1.75" fill="#c49820" stroke="#2a1c08" stroke-width="1"/>
          <rect x="8" y="-8" width="3.5" height="16" rx="1.75" fill="#c49820" stroke="#2a1c08" stroke-width="1"/>
          ${locked ? '<path d="M-3 -1 a3 3 0 0 1 6 0" fill="none" stroke="#2a1c08" stroke-width="1.2"/><rect x="-2" y="-1" width="4" height="3" rx="0.5" fill="#2a1c08"/>' : ""}
        </g>
        <text class="poi-label" y="26" text-anchor="middle" font-family="Caveat,cursive" font-size="11" fill="#2a1c10" font-weight="600">${shortName}</text>`;
    } else {
      g.innerHTML = `
        <circle cx="0" cy="0" r="12" fill="rgba(200,144,42,0.2)" stroke="#c8902a" stroke-width="1.5" stroke-dasharray="4 2"/>
        <text y="5" text-anchor="middle" font-family="Caveat,cursive" font-size="16" fill="#c8902a">+</text>
        <text class="poi-label" y="22" text-anchor="middle" font-family="Caveat,cursive" font-size="10" fill="#9a7860">${shortName}</text>`;
    }

    g.addEventListener("click", (e) => { e.stopPropagation(); onPoiClick(poi); });
    if (highlight.has(poi.id)) g.classList.add("highlight");
    group.appendChild(g);
  });

  const mp = document.getElementById("map-progress");
  if (mp) mp.textContent = `${found} / ${SEED.map.length} discovered`;
}

function renderMap() {
  ensureMap();
  drawMarkers();
}

function onPoiClick(poi) {
  if (!isDiscovered(poi)) { visit(poi); return; }
  const cap = poi.capsuleId ? getPlace(poi.capsuleId) : null;
  if (cap) openCapsule(cap);
  else startCreate(poi);
}

function visit(poi) {
  setTimeout(() => {
    discovered.add(poi.id);
    SoundFX.discover();
    drawMarkers();
    toast(poi.capsuleId ? `Back at ${poi.name}` : `Discovered ${poi.name} — seal a memory here`);
  }, 400);
}

// --- 2. CREATE a capsule ---
let createPoi = null, selMood = null, selCover = null, selFiles = [];
function startCreate(poi) {
  createPoi = poi;
  selMood = SEED.moods[0];
  selCover = SEED.covers[0];
  selFiles = [];
  document.getElementById("file-preview").innerHTML = "";
  document.getElementById("create-files").value = "";
  document.getElementById("filedrop-label").textContent = "＋ add a photo or video — recall reads its EXIF location & time";
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

document.getElementById("create-files").addEventListener("change", (e) => {
  selFiles = [...e.target.files];
  const prev = document.getElementById("file-preview");
  prev.innerHTML = "";
  selFiles.forEach((f) => {
    const url = URL.createObjectURL(f);
    if (f.type.startsWith("video")) {
      prev.insertAdjacentHTML("beforeend", `<video class="fp-item" src="${url}" muted></video>`);
    } else {
      prev.insertAdjacentHTML("beforeend", `<div class="fp-item" style="background:center/cover url('${url}')"></div>`);
      if (!selFiles.some((x, i) => x.type.startsWith("image") && i < selFiles.indexOf(f))) selCover = `center/cover url('${url}')`;
    }
  });
  document.getElementById("filedrop-label").textContent = selFiles.length ? `${selFiles.length} file(s) attached` : "＋ add a photo or video";
});

document.getElementById("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const note = document.getElementById("create-note").value.trim() || "No words — just being here.";
  const id = "c" + Date.now();
  const media = selFiles.map((f) => f.type.startsWith("video")
    ? { type: "video", src: URL.createObjectURL(f) }
    : { type: "photo", src: URL.createObjectURL(f) });
  const cap = {
    id, icon: ICON.capsule, name: createPoi.name, place: createPoi.name,
    visits: "just sealed", sealed: true, mood: selMood, cover: selCover, media,
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

  if (Recall.on()) {
    toast(`Sealing to recall…`);
    const files = [...selFiles];
    if (note && note !== "No words — just being here.") {
      files.push(new File([note], "note.txt", { type: "text/plain" }));
    }
    try {
      await Recall.createCapsule({ place_name: createPoi.name, lat: createPoi.lat, lng: createPoi.lng, files });
      toast(`Sealed at ${cap.name} — ingested by recall.`);
    } catch {
      toast(`Sealed locally (recall unreachable).`);
    }
  } else {
    toast(`Sealed at ${cap.name}. Come back to open it.`);
  }
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

function openingSequence(wasLocked, after) {
  const ov = document.getElementById("opening");
  document.getElementById("opening-text").textContent = wasLocked ? "unearthing…" : "opening…";

  if (reduceMotion) { SoundFX.open(); after(); return; }

  ov.classList.add("show");
  ov.querySelectorAll(".cap3d, .cap-body-wrap, .cap-ground-layer, .cap-top, .cap-bottom, .cap-seam, .cap-burst, .cap-rays, .dust, .wisp").forEach((el) => {
    el.style.animation = "none"; void el.offsetWidth; el.style.animation = "";
  });
  SoundFX.dig();
  if (wasLocked) setTimeout(() => SoundFX.unlock(), 450);
  setTimeout(() => SoundFX.open(), 1000);
  setTimeout(() => { ov.classList.remove("show"); after(); }, 2050);
}

function tracePrinciple(cap) {
  const ids = SEED.map
    .filter((poi) => poi.capsuleId && getPlace(poi.capsuleId) &&
      getPlace(poi.capsuleId).principle === cap.principle)
    .map((poi) => poi.id);
  if (!ids.length && cap.mapId) ids.push(cap.mapId);
  highlight.clear();
  ids.forEach((id) => highlight.add(id));
  switchTab("map");
  drawMarkers();
  SoundFX.shimmer();
  const names = SEED.map.filter((p) => ids.includes(p.id)).map((p) => p.name).join(", ");
  toast(`This principle was formed at: ${names || cap.name}`);
  clearTimeout(highlightTimer);
  highlightTimer = setTimeout(() => { highlight.clear(); drawMarkers(); }, 4500);
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

  const poi = SEED.map.find((m) => m.capsuleId === active.id);
  const coords = poi ? `${poi.lat.toFixed(5)}, ${poi.lng.toFixed(5)}` : "";
  document.getElementById("reveal-meta").innerHTML = `
    <span class="rm-place">${ICON.pin}${active.anchor.place}</span>
    ${coords ? `<span class="rm-coord">${coords}</span>` : ""}
    <span class="rm-time">${active.anchor.time}</span>
    <span class="rm-mood" style="--h:${active.mood.hue}">${active.mood.label} · read by recapsule</span>
    ${active.music ? `<span class="rm-music">♪ ${active.music}</span>` : ""}`;

  const media = active.media && active.media.length
    ? active.media
    : [{ type: "photo", src: (active.anchor.photo.match(/url\(['"]?([^'")]+)/) || [])[1] }];
  document.getElementById("reveal-media").innerHTML = media.map((m) =>
    m.type === "video"
      ? `<video class="rm-item rm-video" src="${m.src}" poster="${m.poster || ""}" muted loop playsinline controls preload="metadata"></video>`
      : (m.src ? `<div class="rm-item rm-photo" style="background:center/cover url('${m.src}')"></div>` : "")
  ).join("");

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
    prinEl.innerHTML = `<span class="plabel">Principle</span><span class="ptext">"${active.principle}"</span><span class="ptrace">tap to light up where this came from →</span>`;
    prinEl.onclick = () => tracePrinciple(cap);
  } else {
    prinEl.style.display = "none";
    prinEl.classList.remove("clickable");
    prinEl.onclick = null;
  }

  document.getElementById("reflection").innerHTML =
    `<div class="rlabel">${ICON.compass} Carry forward</div><div class="rtext">${active.reflection}</div>`;

  document.getElementById("seal-date").textContent = active.sealDate;

  document.getElementById("chat").innerHTML = "";
  addBubble("past", active.opener);
  show("reveal");
}

// --- persona chat ---
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

// --- PRINCIPLE GRAPH (Obsidian-style) ---
let graphNodes = [], graphEdges = [], graphFocus = null;

function buildGraph() {
  const nodes = [];
  const byId = {};
  SEED.principles.forEach((p) => {
    const n = { id: p.id, kind: "principle", label: p.label, text: p.text, conn: new Set() };
    nodes.push(n); byId[p.id] = n;
  });
  SEED.principles.forEach((p) => p.capsules.forEach((cid) => {
    if (!byId[cid]) {
      const cap = getPlace(cid);
      if (!cap) return;
      byId[cid] = { id: cid, kind: "memory", label: cap.name, cover: cap.cover, conn: new Set() };
      nodes.push(byId[cid]);
    }
  }));
  const edges = [];
  SEED.principles.forEach((p) => p.capsules.forEach((cid) => {
    if (byId[cid]) { edges.push({ a: cid, b: p.id, type: "evidence" }); byId[cid].conn.add(p.id); byId[p.id].conn.add(cid); }
  }));
  SEED.principleEdges.forEach((e) => {
    if (byId[e.a] && byId[e.b]) { edges.push({ a: e.a, b: e.b, type: e.type }); byId[e.a].conn.add(e.b); byId[e.b].conn.add(e.a); }
  });
  layoutGraph(nodes, edges, byId);
  graphNodes = nodes; graphEdges = edges;
}

function layoutGraph(nodes, edges, byId) {
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / nodes.length;
    n.x = 50 + 26 * Math.cos(a); n.y = 50 + 26 * Math.sin(a);
  });
  const K = 22;
  for (let it = 0; it < 240; it++) {
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy) || 0.01;
      const rep = ((K * K) / (d * d)) * 5, ux = dx / d, uy = dy / d;
      a.x += ux * rep; a.y += uy * rep; b.x -= ux * rep; b.y -= uy * rep;
    }
    edges.forEach((e) => {
      const a = byId[e.a], b = byId[e.b];
      let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 0.01;
      const att = (d - K) * 0.06, ux = dx / d, uy = dy / d;
      a.x += ux * att; a.y += uy * att; b.x -= ux * att; b.y -= uy * att;
    });
    nodes.forEach((n) => { n.x += (50 - n.x) * 0.012; n.y += (50 - n.y) * 0.012; });
  }
  nodes.forEach((n) => { n.x = Math.max(14, Math.min(86, n.x)); n.y = Math.max(13, Math.min(87, n.y)); });
}

function renderGraph() {
  if (!graphNodes.length) buildGraph();
  const byId = {}; graphNodes.forEach((n) => (byId[n.id] = n));
  const svg = document.getElementById("graph-edges");
  svg.innerHTML = graphEdges.map((e) => {
    const a = byId[e.a], b = byId[e.b];
    const lit = graphFocus && (e.a === graphFocus || e.b === graphFocus);
    return `<line class="${e.type}${lit ? " lit" : ""}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`;
  }).join("");
  svg.classList.toggle("dim", !!graphFocus);

  const wrap = document.getElementById("graph-nodes");
  wrap.innerHTML = "";
  graphNodes.forEach((n, i) => {
    const el = document.createElement("button");
    el.className = `gnode ${n.kind}`;
    if (graphFocus) {
      if (n.id === graphFocus || byId[graphFocus].conn.has(n.id)) el.classList.add("lit");
      else el.classList.add("dim");
    }
    el.style.left = n.x + "%"; el.style.top = n.y + "%";
    el.style.animationDelay = (-i * 0.7) + "s";
    const dot = n.kind === "memory" ? `<span class="gdot"></span>` : `<span class="gdot"></span>`;
    el.innerHTML = `${dot}<span class="glabel">${n.label}</span>`;
    el.setAttribute("aria-label", n.kind === "memory" ? `Open ${n.label}` : `Principle: ${n.text}`);
    el.addEventListener("click", (ev) => { ev.stopPropagation(); onGraphNode(n); });
    wrap.appendChild(el);
  });
}

function onGraphNode(n) {
  if (n.kind === "memory") { openCapsule(getPlace(n.id)); return; }
  graphFocus = (graphFocus === n.id) ? null : n.id;
  SoundFX.shimmer();
  renderGraph();
  document.getElementById("graph-info").textContent = graphFocus
    ? `"${n.text}" — tap a lit memory to open it.`
    : "Tap a principle to see the moments behind it. Tap a memory to open it.";
}
document.getElementById("graph").addEventListener("click", () => {
  if (graphFocus) { graphFocus = null; renderGraph(); document.getElementById("graph-info").textContent = "Tap a principle to see the moments behind it. Tap a memory to open it."; }
});

// --- tabs + back nav ---
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
document.querySelectorAll("[data-back-map]").forEach((b) => b.addEventListener("click", () => show("map")));

// --- home screen logo goes home ---
document.getElementById("logo-home").addEventListener("click", () => show("home"));

// --- HOME: capsule choice buttons ---
document.getElementById("btn-viewmap").addEventListener("click", () => {
  SoundFX.tap();
  show("map");
  renderMap();
});

document.getElementById("btn-digdrop").addEventListener("click", () => {
  SoundFX.tap();
  show("discover");
});

// --- DISCOVER screen buttons ---
document.getElementById("btn-dig-old").addEventListener("click", () => {
  show("places");
  renderPlaces();
});
document.getElementById("btn-drop-new").addEventListener("click", () => {
  openCameraScreen();
});

// --- all [data-goto-home] elements → home ---
document.querySelectorAll("[data-goto-home]").forEach((b) =>
  b.addEventListener("click", () => { closeCameraStream(); show("home"); })
);

// --- COMPASS on map view: spin needle then go to graph ---
const compassEl = document.getElementById("compass");
const compassNeedle = document.getElementById("compass-needle");

compassEl.addEventListener("click", () => {
  SoundFX.shimmer();
  // remove class first to allow re-triggering
  compassNeedle.classList.remove("spin-once");
  // force reflow so re-add triggers animation
  void compassNeedle.offsetWidth;
  compassNeedle.classList.add("spin-once");

  // after spin completes (1.2s) go to graph
  compassNeedle.addEventListener("animationend", function onSpinEnd() {
    compassNeedle.removeEventListener("animationend", onSpinEnd);
    compassNeedle.classList.remove("spin-once");
    switchTab("graph");
    renderGraph();
  }, { once: true });
});

// --- camera / drag screen logic ---
document.getElementById("btn-start-dig").addEventListener("click", openDragScreen);

let cameraStream = null;
async function openCameraScreen() {
  show("camera");
  const video = document.getElementById("camera-feed");
  const cameraWrap = document.getElementById("camera-wrap-el");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    if (video) { video.srcObject = stream; cameraStream = stream; }
    if (cameraWrap) cameraWrap.classList.add("has-camera");
  } catch {
    if (cameraWrap) cameraWrap.classList.remove("has-camera");
  }
  // setup swipe gesture
  initCameraSwipe();
}

function closeCameraStream() {
  if (cameraStream) { cameraStream.getTracks().forEach((t) => t.stop()); cameraStream = null; }
}

// --- swipe gesture detection on camera screen ---
function initCameraSwipe() {
  const wrap = document.getElementById("camera-wrap-el");
  if (!wrap || wrap._swipeInited) return;
  wrap._swipeInited = true;

  let touchStartX = 0;
  wrap.addEventListener("touchstart", (e) => {
    touchStartX = e.touches[0].clientX;
  }, { passive: true });
  wrap.addEventListener("touchend", (e) => {
    const delta = e.changedTouches[0].clientX - touchStartX;
    if (Math.abs(delta) > 60) {
      openDragScreen();
    }
  }, { passive: true });
}

// --- drag screen ---
function openDragScreen() {
  closeCameraStream();
  show("drag");
  initDrag();
}

function initDrag() {
  const capsuleOrig = document.getElementById("drag-capsule");
  const stumpScene = document.querySelector(".stump-scene");
  const scene = document.getElementById("drag-scene");
  if (!capsuleOrig || !stumpScene || !scene) return;

  // reset
  capsuleOrig.style.transition = "";
  capsuleOrig.style.top = "20px";
  stumpScene.classList.remove("receiving");

  let dragging = false, startY = 0, curY = 0;
  const GROUND_THRESH = scene.offsetHeight - 200;

  const onStart = (e) => {
    dragging = true;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    const rect = capsuleOrig.getBoundingClientRect();
    startY = clientY - rect.top;
    capsuleOrig.style.transition = "none";
    e.preventDefault();
  };
  const onMove = (e) => {
    if (!dragging) return;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    const sceneRect = scene.getBoundingClientRect();
    curY = Math.min(GROUND_THRESH, Math.max(0, clientY - sceneRect.top - startY));
    capsuleOrig.style.top = curY + "px";
    if (curY >= GROUND_THRESH - 20) stumpScene.classList.add("receiving");
    else stumpScene.classList.remove("receiving");
    e.preventDefault();
  };
  const onEnd = () => {
    if (!dragging) return;
    dragging = false;
    if (curY >= GROUND_THRESH - 30) {
      // burial animation: sink + scale down
      capsuleOrig.style.transition = "top .35s ease-in, transform .35s ease-in, opacity .3s .15s ease";
      capsuleOrig.style.top = (GROUND_THRESH + 80) + "px";
      capsuleOrig.style.transform = "translateX(-50%) scale(0.5)";
      capsuleOrig.style.opacity = "0";

      // soil particles burst
      capsuleOrig.querySelectorAll(".soil-particle").forEach((p) => {
        p.classList.add("burst");
      });

      setTimeout(() => {
        capsuleOrig.style.transition = "";
        capsuleOrig.style.top = "20px";
        capsuleOrig.style.transform = "translateX(-50%)";
        capsuleOrig.style.opacity = "1";
        capsuleOrig.querySelectorAll(".soil-particle").forEach((p) => p.classList.remove("burst"));
        stumpScene.classList.remove("receiving");
        const poi = SEED.map.find((p) => !p.capsuleId) || SEED.map[0];
        startCreate(poi);
      }, 600);
    } else {
      capsuleOrig.style.transition = "top .3s var(--easing)";
      capsuleOrig.style.top = "20px";
    }
  };

  // clean up old listeners by cloning
  const newCapsule = capsuleOrig.cloneNode(true);
  capsuleOrig.parentNode.replaceChild(newCapsule, capsuleOrig);

  newCapsule.addEventListener("mousedown", onStart);
  newCapsule.addEventListener("touchstart", onStart, { passive: false });
  document.addEventListener("mousemove", onMove);
  document.addEventListener("touchmove", onMove, { passive: false });
  document.addEventListener("mouseup", onEnd);
  document.addEventListener("touchend", onEnd);
}

// --- pull any capsules already ingested by the recall backend ---
async function hydrateFromBackend() {
  if (!Recall.on()) return;
  const list = await Recall.listCapsules();
  setBackendChip(list !== null);
  if (!list) return;
  let added = 0;
  list.forEach((c) => {
    if (getPlace(c.id)) return;
    const cap = Recall.toUICapsule(c);
    SEED.places.push(cap);
    if (cap._lat != null && cap._lng != null) {
      SEED.map.push({ id: c.id, name: cap.name, lat: cap._lat, lng: cap._lng, discovered: true, capsuleId: c.id });
    }
    added++;
  });
  if (added) { renderMap(); renderPlaces(); buildGraph(); renderGraph(); }
}
function setBackendChip(live) {
  const el = document.getElementById("map-progress");
  if (el) el.title = live ? "recall backend: connected" : "recall backend: offline (seed)";
}

// --- boot ---
renderMap();
renderPlaces();
renderGraph();
show("home");
hydrateFromBackend();

if (location.search.includes("demo=venue")) { active = getPlace("venue"); reveal(); }
if (location.search.includes("demo=map")) { show("map"); renderMap(); }
if (location.search.includes("demo=principles")) { show("graph"); renderGraph(); }
if (location.search.includes("demo=discover")) { show("discover"); }
if (location.search.includes("demo=places")) { show("places"); }
