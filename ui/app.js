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

// runtime state. Capsules have no lock state — every one opens directly. The
// only gating left is the map's fog-of-war: undiscovered pins you "travel" to.
const discovered = new Set(SEED.map.filter((m) => m.discovered).map((m) => m.id));
const isDiscovered = (poi) => discovered.has(poi.id);

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
  graph: document.getElementById("view-graph"),
  places: document.getElementById("view-places"),
  create: document.getElementById("view-create"),
  reconstruct: document.getElementById("view-reconstruct"),
  reveal: document.getElementById("view-reveal"),
};
const FLOW = ["create", "reconstruct", "reveal"]; // hide tab bar in these
const TAB_FOR_VIEW = { map: "map", graph: "graph", places: "capsules" };
function show(name) {
  Object.values(views).forEach((v) => v.classList.remove("active"));
  views[name].classList.add("active");
  document.getElementById("tabbar").classList.toggle("hidden", FLOW.includes(name));
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", TAB_FOR_VIEW[name] === t.dataset.tab));
  document.querySelector(".screen").scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
  // The map view just became visible, so its container now has a real size —
  // (re)initialize and reframe the map against that size. This is also the path
  // that fixes the "pins in the corner" symptom: the map is never drawn while
  // hidden/0-sized, only here, once #map is actually laid out.
  if (name === "map") refreshMapView();
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

// --- 1. LIVE SATELLITE MAP (MapLibre + Esri World Imagery) ---
// Rebuilt from scratch. The previous version initialized MapLibre while its
// container was still hidden/0-sized (boot ran before the view was shown, behind
// an async lock gate), so every marker projected to the top-left origin and the
// pins clumped in the corner. A pile of setTimeout(resize/redraw) hacks tried to
// recover and were flaky.
//
// This version is built on one invariant: NOTHING touches the map until its
// container has a real, non-zero layout size. `whenMapSized()` resolves only
// once #map measures > 0, and every public entry point (ensureMap/renderMap/
// drawMarkers/fitToMarkers) is a no-op until both the style has loaded AND the
// container is sized (`mapReady`). Markers are therefore only ever projected
// against a correctly-sized viewport — they can't land in the corner.
const MAP_CENTER = [-122.2588, 37.8698]; // Berkeley Southside (real photo cluster)
const MAP_ZOOM = 15.4;
let map = null;            // the MapLibre instance (null until the container is sized)
let markerObjs = [];       // live maplibregl.Marker objects, cleared on every redraw
let mapReady = false;      // true once style is loaded AND container is sized
let mapInitStarted = false; // guards against constructing the map twice

const mapEl = () => document.getElementById("map");
const isSized = (el) => !!el && el.clientWidth > 0 && el.clientHeight > 0;

// Resolve once #map has a real laid-out size. ResizeObserver fires as soon as the
// box is measured; we also check synchronously in case it's already sized.
function whenMapSized() {
  return new Promise((resolve) => {
    const el = mapEl();
    if (!el) return; // no container → never resolves; nothing to draw anyway
    if (isSized(el)) { resolve(el); return; }
    if ("ResizeObserver" in window) {
      const ro = new ResizeObserver(() => {
        if (isSized(el)) { ro.disconnect(); resolve(el); }
      });
      ro.observe(el);
    } else {
      // No ResizeObserver: poll on animation frames until the box has a size.
      const tick = () => (isSized(el) ? resolve(el) : requestAnimationFrame(tick));
      requestAnimationFrame(tick);
    }
  });
}

const SAT_STYLE = {
  version: 8,
  sources: {
    sat: {
      type: "raster", tileSize: 256,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Imagery © Esri",
    },
  },
  layers: [{ id: "sat", type: "raster", source: "sat" }],
};

// Construct the MapLibre instance — but only after the container is sized, so the
// canvas and every marker project against the real viewport from the very first
// frame. Idempotent: safe to call repeatedly; the real work runs at most once.
function ensureMap() {
  if (mapInitStarted || typeof maplibregl === "undefined") return;
  mapInitStarted = true;
  whenMapSized().then((el) => {
    map = new maplibregl.Map({
      container: el,
      style: SAT_STYLE,          // Esri satellite raster — without this the map is black
      attributionControl: false,
      center: MAP_CENTER, zoom: MAP_ZOOM, pitch: 0, bearing: 0,
      // The container is sized, so MapLibre measures the right dimensions itself.
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }));
    map.on("load", () => {
      mapReady = true;
      el.classList.add("ready"); // one-time fade-in
      drawMarkers();
      fitToMarkers();
    });
    // If the box later changes size (orientation, tab re-show), keep the canvas
    // and marker projection in sync. No redraw-on-a-timer guesswork.
    if ("ResizeObserver" in window) {
      new ResizeObserver(() => { if (map) map.resize(); }).observe(el);
    }
  });
}

function stopSpin() {} // map no longer auto-moves (kept for callers)

// Frame ALL pins so they fit the viewport with margin. fitBounds derives the
// right center+zoom from the pins' bounding box; a single pin gets a fixed zoom;
// no pins falls back to the default Berkeley framing.
function fitToMarkers() {
  if (!mapReady || !map) return;
  const pts = SEED.map.filter((m) => m.lat != null && m.lng != null);
  if (!pts.length) { map.jumpTo({ center: MAP_CENTER, zoom: MAP_ZOOM, pitch: 0, bearing: 0 }); return; }
  if (pts.length === 1) {
    map.jumpTo({ center: [pts[0].lng, pts[0].lat], zoom: 16, pitch: 0, bearing: 0 });
    return;
  }
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
  for (const m of pts) {
    minLng = Math.min(minLng, m.lng); maxLng = Math.max(maxLng, m.lng);
    minLat = Math.min(minLat, m.lat); maxLat = Math.max(maxLat, m.lat);
  }
  map.fitBounds([[minLng, minLat], [maxLng, maxLat]], {
    padding: { top: 60, bottom: 60, left: 50, right: 50 },
    maxZoom: 16.5,
    duration: 0,    // instant (no fly-in), consistent with the static map
    pitch: 0, bearing: 0,
  });
}

// Build one marker element for a POI (fog / capsule / empty).
//
// CRITICAL: MapLibre positions a marker by writing `transform: translate(x,y)`
// onto the *element it's given*. Our marker CSS animates/transforms `.mk` (the
// `mkin` sketch-in keyframe + hover/active scale), and an animated `transform`
// OVERRIDES MapLibre's positioning translate — which snapped every pin to the map
// origin (the "stuck in the top-left corner" bug). The fix: hand MapLibre a plain
// wrapper it can freely transform, and put the styled/animated `.mk` element
// INSIDE it. MapLibre moves the wrapper; our CSS only ever transforms the child.
function markerElement(poi) {
  const disc = isDiscovered(poi);
  const cap = poi.capsuleId ? getPlace(poi.capsuleId) : null;

  const wrapper = document.createElement("div"); // MapLibre owns this transform
  const el = document.createElement("button");   // our styled/animated marker
  el.className = "mk";
  let inner;
  if (!disc) {
    el.classList.add("fog");
    el.setAttribute("aria-label", `Locked — travel to ${poi.name} to discover it`);
    inner = `<span class="mk-dot">${ICON.lock}</span><span class="mk-label">${poi.name}</span>`;
  } else if (cap) {
    el.classList.add("cap");
    el.setAttribute("aria-label", `Open capsule — ${poi.name}`);
    inner = `<span class="mk-dot"><span class="mk-seam"></span></span><span class="mk-label">${poi.name}</span>`;
  } else {
    el.classList.add("empty");
    el.setAttribute("aria-label", `Seal a capsule at ${poi.name}`);
    inner = `<span class="mk-dot">${ICON.plus}</span><span class="mk-label">${poi.name}</span>`;
  }
  if (highlight.has(poi.id)) el.classList.add("highlight");
  el.innerHTML = inner;
  el.addEventListener("click", (e) => { e.stopPropagation(); onPoiClick(poi); });
  wrapper.appendChild(el);
  return wrapper;
}

// Rebuild all markers from SEED.map. No-op until the map is ready, so a marker is
// never placed against a 0-sized viewport. Skips POIs missing coordinates.
function drawMarkers() {
  if (!mapReady || !map) return;
  markerObjs.forEach((m) => m.remove());
  markerObjs = [];
  let found = 0;
  SEED.map.forEach((poi) => {
    if (poi.lat == null || poi.lng == null) return; // can't place without coords
    if (isDiscovered(poi)) found++;
    const marker = new maplibregl.Marker({ element: markerElement(poi), anchor: "center" })
      .setLngLat([poi.lng, poi.lat])
      .addTo(map);
    markerObjs.push(marker);
  });
  const mp = document.getElementById("map-progress");
  if (mp) mp.textContent = `${found}/${SEED.map.length} discovered`;
}

// Public entry point the rest of the app calls. Kicks off init (once), and once
// the map is ready, refreshes the markers. Calls made before the map is ready are
// harmless — the load handler does the first draw, and later calls redraw.
function renderMap() {
  ensureMap();
  if (mapReady) drawMarkers();
}

// Called by show("map"): the container may have just gained its size, so make
// sure the map is initialized and (once ready) resized + reframed to its pins.
function refreshMapView() {
  ensureMap();
  if (!mapReady || !map) return;
  map.resize();
  drawMarkers();
}

// Move the camera to a point — safe to call before the map exists or has loaded
// (e.g. right after the very first capsule is sealed, while the map is still
// initializing). If not ready yet, the move is deferred to the load handler.
function flyTo(lng, lat, zoom = 16) {
  ensureMap();
  const go = () => map.easeTo({ center: [lng, lat], zoom, duration: 700, essential: true });
  if (mapReady && map) { go(); return; }
  whenMapSized().then(() => {
    if (mapReady) go();
    else map && map.once("load", go);
  });
}

function onPoiClick(poi) {
  if (!isDiscovered(poi)) { visit(poi); return; }
  const cap = poi.capsuleId ? getPlace(poi.capsuleId) : null;
  if (cap) openCapsule(cap);
  else startCreate(poi);
}

// travel to a locked spot, then discover it
function visit(poi) {
  stopSpin();
  flyTo(poi.lng, poi.lat, 16.6);
  setTimeout(() => {
    discovered.add(poi.id);
    SoundFX.discover();
    drawMarkers();
    toast(poi.capsuleId ? `Back at ${poi.name}` : `Discovered ${poi.name} — seal a memory here`);
  }, 1500);
}

// --- 2. CREATE a capsule ---
let createPoi = null, selCover = null, selFiles = [];

// Shared reset for the create form, used by both entry paths (a map pin, or a
// standalone "New capsule" with a user-named place).
function resetCreateForm() {
  selCover = null; // the uploaded photo becomes the cover; no preset picker
  selFiles = [];
  document.getElementById("file-preview").innerHTML = "";
  document.getElementById("create-files").value = "";
  document.getElementById("filedrop-label").textContent = "＋ add a photo or video — recall reads its EXIF location & time";
  document.getElementById("create-loc-icon").innerHTML = ICON.pin;
  document.getElementById("create-note").value = "";
  // clear any pin from a previous create session
  if (createMarker) { createMarker.remove(); createMarker = null; }
  const hint = document.getElementById("create-loc-hint");
  if (hint) hint.textContent = "Tap the map to drop this capsule’s pin.";
}

// From a discovered map pin: place name + location come from the pin (still
// adjustable by tapping the create map).
function startCreate(poi) {
  createPoi = poi;
  resetCreateForm();
  const place = document.getElementById("create-place");
  place.value = poi.name;
  place.readOnly = true;
  show("create");
  ensureCreateMap();
  if (poi.lat != null && poi.lng != null) {
    setCreateLocation(poi.lat, poi.lng, true);
    if (createMap) createMap.jumpTo({ center: [poi.lng, poi.lat], zoom: 15 });
  }
}

// --- create-view location picker (tap the map to drop the capsule's pin) ---
let createMap = null, createMarker = null;

function setCreateLocation(lat, lng, silent) {
  if (!createPoi) return;
  createPoi.lat = lat;
  createPoi.lng = lng;
  if (createMap) {
    if (!createMarker) {
      const el = document.createElement("div");
      el.className = "create-pin";
      createMarker = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([lng, lat]).addTo(createMap);
    } else {
      createMarker.setLngLat([lng, lat]);
    }
  }
  const hint = document.getElementById("create-loc-hint");
  if (hint && !silent) hint.textContent = `Pinned at ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

function ensureCreateMap() {
  if (typeof maplibregl === "undefined") return;
  if (!createMap) {
    createMap = new maplibregl.Map({
      container: "create-map",
      attributionControl: false,
      center: MAP_CENTER, zoom: 13, pitch: 0, bearing: 0,
      style: {
        version: 8,
        sources: { sat: {
          type: "raster", tileSize: 256,
          tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
          attribution: "Imagery © Esri",
        } },
        layers: [{ id: "sat", type: "raster", source: "sat" }],
      },
    });
    // tap anywhere to (re)place the capsule's pin
    createMap.on("click", (e) => setCreateLocation(e.lngLat.lat, e.lngLat.lng));
  }
  // it's freshly shown, so size it correctly (same race as the main map)
  [60, 250, 600].forEach((ms) => setTimeout(() => createMap && createMap.resize(), ms));
}

// Standalone: no pin yet. The user names the place and TAPS the map to set the
// location (a capsule is a place + journal + media, flywheel §3). Geolocation is
// only a prefill — tap-to-place is what reliably works on http/mobile.
function startCreateStandalone() {
  createPoi = { id: `cap-${Date.now()}`, name: "", lat: null, lng: null, standalone: true };
  resetCreateForm();
  const place = document.getElementById("create-place");
  place.value = "";
  place.readOnly = false;
  show("create");
  place.focus();
  // Tap-to-place is the reliable location path (works on http/mobile, unlike
  // geolocation which needs HTTPS). Geolocation is only a best-effort prefill
  // that re-centers the picker if it resolves before the user taps.
  ensureCreateMap();
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (createPoi && createPoi.lat == null) {  // don't override a user tap
          setCreateLocation(pos.coords.latitude, pos.coords.longitude, true);
          if (createMap) createMap.jumpTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 15 });
        }
      },
      () => {},
      { enableHighAccuracy: false, timeout: 4000, maximumAge: 60000 }
    );
  }
}

// real photo/video attach — first image becomes the cover; all files upload to recall
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
  // Place name comes from the (now editable) field; required, per the API.
  const placeName = document.getElementById("create-place").value.trim();
  if (!placeName) {
    toast("Give this place a name first.");
    document.getElementById("create-place").focus();
    return;
  }
  createPoi.name = placeName;
  const note = document.getElementById("create-note").value.trim() || "No words — just being here.";
  const id = "c" + Date.now();
  const media = selFiles.map((f) => f.type.startsWith("video")
    ? { type: "video", src: URL.createObjectURL(f) }
    : { type: "photo", src: URL.createObjectURL(f) });
  // Cover = the first uploaded photo, else a warm gradient fallback.
  const firstPhoto = media.find((m) => m.type === "photo");
  const cover = selCover || (firstPhoto
    ? `center/cover url('${firstPhoto.src}')`
    : "linear-gradient(150deg,#2a2140 0%,#4a3a5e 55%,#cf7f86 130%)");
  const cap = {
    id, icon: ICON.capsule, name: createPoi.name, place: createPoi.name,
    visits: "just sealed", sealed: true, cover, media,
    storyline: escapeHTML(note),
    citations: [], principle: "",
    reflection: "When you open this, what will you want to remember about who you are today?",
    sealDate: "sealed just now",
    opener: "what were you hoping for when you sealed this?",
    replies: [], fallback: "I sealed this moment for you — that's all I know yet.",
    anchor: { place: createPoi.name, time: "just now", photo: cover },
    userCreated: true,
  };
  const hasCoords = createPoi.lat != null && createPoi.lng != null;

  // Backend path: the backend is the source of truth. Send it, then re-hydrate so
  // the capsule appears exactly once with its persisted id + coords (no duplicate
  // optimistic copy, which was causing capsules to show twice / mis-located).
  if (Recall.on()) {
    toast("Sealing to recall…");
    const files = [...selFiles];
    if (note && note !== "No words — just being here.") {
      files.push(new File([note], "note.txt", { type: "text/plain" }));
    }
    try {
      const saved = await Recall.createCapsule({
        place_name: createPoi.name,
        lat: createPoi.lat, lng: createPoi.lng, files,
      });
      await hydrateFromBackend();          // single source of truth → no dupes
      const savedPoi = SEED.map.find((m) => m.capsuleId === (saved && saved.id));
      renderMap(); renderPlaces();
      if (savedPoi) {
        switchTab("map");
        flyTo(savedPoi.lng, savedPoi.lat, 16);
      } else {
        switchTab("capsules");             // no coords → lives in the list
      }
      toast(`Sealed at ${createPoi.name} — ingested by recall.`);
    } catch {
      toast("Couldn’t reach recall — capsule not saved.");
    }
    return;
  }

  // No backend (seed/offline mode): keep the optimistic local capsule so the UI
  // still works standalone.
  SEED.places.push(cap);
  createPoi.capsuleId = id;
  if (hasCoords && !SEED.map.some((m) => m.id === createPoi.id)) {
    SEED.map.push({
      id: createPoi.id, name: createPoi.name, lat: createPoi.lat, lng: createPoi.lng,
      discovered: true, capsuleId: id,
    });
    cap.mapId = createPoi.id;
  }
  discovered.add(createPoi.id);
  renderMap();
  renderPlaces();
  switchTab(hasCoords ? "map" : "capsules");
  toast(`Sealed at ${cap.name}.`);
});

// --- 3. CAPSULES tab ---
function renderPlaces() {
  const list = document.getElementById("place-list");
  list.innerHTML = "";
  getPlaces().forEach((p) => {
    const el = document.createElement("article");
    el.className = "place";
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", `Open capsule at ${p.name}`);
    el.innerHTML = `
      <div class="place-cover" style="background:${p.cover}"></div>
      <div class="place-scrim"></div>
      <div class="place-glyph">${p.icon}</div>
      <div class="place-top">
        <span class="place-loc">${ICON.pin}${p.place}</span>
      </div>
      <div class="place-body">
        <h3 class="pname">${p.name}</h3>
        <div class="pmeta">${p.visits || ""}</div>
      </div>`;
    const go = () => openCapsule(p);
    el.addEventListener("click", go);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
    list.appendChild(el);
  });
}

// open a capsule — big open animation (~80% screen) + sound, then the same
// reveal page you'd see right after sealing it. (No lock/unearth state: every
// capsule opens directly.)
function openCapsule(cap) {
  active = cap;
  const proceed = () => { if (cap.cues && cap.cues.length) openPlace(cap.id); else reveal(); };
  openingSequence(proceed);
}

// the big capsule graphic + open sound, then the page
function openingSequence(after) {
  const ov = document.getElementById("opening");
  document.getElementById("opening-text").textContent = "opening…";

  if (reduceMotion) { SoundFX.open(); after(); return; }

  ov.classList.add("show");
  // restart the capsule open animations
  ov.querySelectorAll(".cap3d, .cap-top, .cap-bottom, .cap-burst, .cap-rays, .dust").forEach((el) => {
    el.style.animation = "none"; void el.offsetWidth; el.style.animation = "";
  });
  // sound: dig as it rises, then the "pop" as the lid opens (~1s in)
  SoundFX.dig();
  setTimeout(() => SoundFX.open(), 1000);

  setTimeout(() => { ov.classList.remove("show"); after(); }, 2050);
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
  stopSpin();
  drawMarkers();
  SoundFX.shimmer();
  const target = SEED.map.find((p) => ids.includes(p.id));
  if (target) flyTo(target.lng, target.lat, 16);
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

  // --- capsule data model: place · coordinates · time · music
  const poi = SEED.map.find((m) => m.capsuleId === active.id);
  const coords = poi ? `${poi.lat.toFixed(5)}, ${poi.lng.toFixed(5)}` : "";
  document.getElementById("reveal-meta").innerHTML = `
    <span class="rm-place">${ICON.pin}${active.anchor.place}</span>
    ${coords ? `<span class="rm-coord">${coords}</span>` : ""}
    <span class="rm-time">${active.anchor.time}</span>
    ${active.music ? `<span class="rm-music">♪ ${active.music}</span>` : ""}`;

  // --- media: photos + video (text lives in the storyline below)
  const coverPhoto = (active.anchor && active.anchor.photo) || "";
  const media = active.media && active.media.length
    ? active.media
    : [{ type: "photo", src: (coverPhoto.match(/url\(['"]?([^'")]+)/) || [])[1] }];
  document.getElementById("reveal-media").innerHTML = media.map((m) =>
    m.type === "video"
      ? `<video class="rm-item rm-video" src="${m.src}" poster="${m.poster || ""}" muted loop playsinline controls preload="metadata"></video>`
      : (m.src ? `<div class="rm-item rm-photo" style="background:center/cover url('${m.src}')"></div>` : "")
  ).join("");

  const html = (active.storyline || "").replace(/\*([^*]+)\*/g, "<em>$1</em>")
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

// tiny force-directed layout in 0..100 space
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
    const dot = n.kind === "memory" ? `<span class="gdot" style="background:${n.cover}"></span>` : `<span class="gdot"></span>`;
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
    ? `“${n.text}” — tap a lit memory to open it.`
    : "Tap a principle to see the moments behind it. Tap a memory to open it.";
}
document.getElementById("graph").addEventListener("click", () => {
  if (graphFocus) { graphFocus = null; renderGraph(); document.getElementById("graph-info").textContent = "Tap a principle to see the moments behind it. Tap a memory to open it."; }
});

// --- tabs + back nav ---
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
document.querySelectorAll("[data-back-map]").forEach((b) => b.addEventListener("click", () => show("map")));

// --- "create a capsule" entry point: the Capsules-tab button (the map FAB was
// removed — it didn't fit the home view). ---
document.getElementById("create-capsule-btn").addEventListener("click", startCreateStandalone);

// --- pull any capsules already ingested by the recall backend (capsule-ingest) ---
async function hydrateFromBackend() {
  if (!Recall.on()) return;
  const list = await Recall.listCapsules(); // null = unreachable, [] = connected but empty
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

// --- passcode lock gate (local-first auth) ---
// If the backend requires a passcode and we don't have a valid one yet, show the
// themed lock screen and wait for a correct unlock before booting the app.
async function lockGate() {
  if (!Recall.on()) return true; // no backend (file:// / seed mode) → nothing to lock
  let required;
  try { required = await Recall.authRequired(); }
  catch { return true; } // backend unreachable → seed mode, no lock
  if (!required) return true;
  // already have a token? verify it silently.
  if (Recall.getToken() && (await Recall.unlock(Recall.getToken()))) return true;

  const lock = document.getElementById("lock");
  const form = document.getElementById("lock-form");
  const input = document.getElementById("lock-input");
  const err = document.getElementById("lock-error");
  lock.hidden = false;
  input.focus();
  return new Promise((resolve) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      const ok = await Recall.unlock(input.value.trim());
      if (ok) { lock.hidden = true; resolve(true); }
      else {
        err.textContent = "Incorrect passcode.";
        input.classList.remove("shake"); void input.offsetWidth; input.classList.add("shake");
        input.select();
      }
    });
  });
}

// --- boot ---
async function boot() {
  renderMap();
  renderPlaces();
  renderGraph();
  show("map");
  await lockGate();
  hydrateFromBackend();
  if (location.search.includes("demo=venue")) { active = getPlace("venue"); reveal(); }
}
boot();
