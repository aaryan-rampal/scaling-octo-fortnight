/* recall backend client — incorporates the `capsule-ingest` branch.
 *
 * Talks to the FastAPI `recall` server (poc_demo/server, default :8000):
 *   GET  /api/health
 *   GET  /api/capsules            -> [{id, created_at, place_name, lat, lng, media:[Media]}]
 *   POST /api/capsules            (multipart: place_name, lat, lng, files[])
 *   GET  /api/networks            -> {episodic, semantic, people, principles:[{name,content}], connections}
 *   media served at  /media/<file_path>
 *
 * The UI stays a static app: if no backend is configured/reachable it falls back
 * to seed.js. Point it at a server by running this in the console (or setting it
 * before load):  localStorage.recall_api = "http://localhost:8000"
 */
const Recall = (() => {
  // Resolve the backend base URL, in priority order:
  //   1. an explicit override (window.RECALL_API or localStorage.recall_api)
  //   2. same-origin — when the page is served over http(s) by `recall serve`,
  //      the backend IS this origin, so the UI just works with no config (this
  //      is also what makes phone-over-wifi work: the phone's origin is the
  //      laptop's IP, which is exactly the backend).
  //   3. "" — e.g. opened as a file:// with no backend → falls back to seed.js.
  const sameOrigin = () =>
    location.protocol.startsWith("http") ? location.origin : "";
  const base = () =>
    (window.RECALL_API || localStorage.getItem("recall_api") || sameOrigin()).replace(/\/$/, "");
  const on = () => !!base();

  // ── passcode (local-first auth) ───────────────────────────────────────
  // The passcode the lock screen collects, sent as X-Recall-Token on every
  // request. Persisted so an unlocked device stays unlocked across reloads.
  let _token = localStorage.getItem("recall_token") || "";
  const getToken = () => _token;
  const setToken = (t) => { _token = t || ""; localStorage.setItem("recall_token", _token); };
  const clearToken = () => { _token = ""; localStorage.removeItem("recall_token"); };
  const authHeaders = () => (_token ? { "X-Recall-Token": _token } : {});
  // <img>/<video> can't send headers, so media carries the token as a query param
  // (the backend accepts it there too).
  const mediaURL = (fp) =>
    `${base()}/media/${fp}` + (_token ? `?t=${encodeURIComponent(_token)}` : "");

  async function health() {
    if (!on()) return null;
    try { const r = await fetch(base() + "/api/health", { cache: "no-store" }); return r.ok ? await r.json() : null; }
    catch { return null; }
  }
  // True if the backend requires a passcode (health reports it).
  async function authRequired() {
    const h = await health();
    return !!(h && h.auth_required);
  }
  // Try a passcode against a protected endpoint; on success it's saved. Returns
  // true if accepted, false if rejected (401).
  async function unlock(passcode) {
    try {
      const r = await fetch(base() + "/api/capsules", {
        headers: { "X-Recall-Token": passcode },
      });
      if (r.status === 401) return false;
      if (!r.ok) return false;
      setToken(passcode);
      return true;
    } catch { return false; }
  }
  // returns the capsules array, or null if the backend is unreachable
  async function listCapsules() {
    if (!on()) return null;
    try {
      const r = await fetch(base() + "/api/capsules", { headers: authHeaders() });
      if (!r.ok) return null;
      const j = await r.json();
      return Array.isArray(j) ? j : (j.capsules || []); // server wraps as {capsules:[...]}
    } catch { return null; }
  }
  async function createCapsule({ place_name, lat, lng, files }) {
    const fd = new FormData();
    fd.append("place_name", place_name);
    if (lat != null) fd.append("lat", lat);
    if (lng != null) fd.append("lng", lng);
    (files || []).forEach((f) => fd.append("media", f)); // server field is `media` (list[UploadFile])
    const r = await fetch(base() + "/api/capsules", { method: "POST", body: fd, headers: authHeaders() });
    if (!r.ok) throw new Error("create " + r.status);
    return await r.json();
  }
  async function networks() {
    if (!on()) return null;
    try { const r = await fetch(base() + "/api/networks", { headers: authHeaders() }); return r.ok ? await r.json() : null; }
    catch { return null; }
  }

  // map a backend Capsule -> the UI's capsule shape (seed.js compatible)
  function toUICapsule(c) {
    const photo = (c.media || []).find((m) => m.kind === "photo");
    const cover = photo
      ? `center/cover url('${mediaURL(photo.file_path)}')`
      : "linear-gradient(150deg,#2a2140 0%,#4a3a5e 55%,#cf7f86 130%)";
    const media = (c.media || [])
      .map((m) => (m.kind === "video" ? { type: "video", src: mediaURL(m.file_path) }
        : m.kind === "photo" ? { type: "photo", src: mediaURL(m.file_path) } : null))
      .filter(Boolean);
    const lat = c.lat ?? (photo && photo.exif_lat) ?? null;
    const lng = c.lng ?? (photo && photo.exif_lng) ?? null;
    const when = (c.created_at || "").replace("T", " ").slice(0, 16);
    return {
      id: c.id, icon: (typeof ICON !== "undefined" ? ICON.capsule : ""),
      name: c.place_name, place: c.place_name, visits: "from recall",
      sealed: false, mood: { label: "captured", hue: 200 }, music: null,
      cover, media,
      anchor: { place: c.place_name, time: when, photo: cover },
      cues: [], citations: [], principle: "",
      reflection: "What do you want to carry forward from this?",
      sealDate: "ingested by recall · " + (c.created_at || "").slice(0, 10),
      opener: "what was this moment?", replies: [], fallback: "A captured memory.",
      userCreated: true, _lat: lat, _lng: lng,
    };
  }

  return {
    base, on, health, authRequired, unlock, getToken, setToken, clearToken,
    listCapsules, createCapsule, networks, toUICapsule, mediaURL,
  };
})();
