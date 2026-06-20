/* RETURN — frontend controller.
 * Drives the reconstruct-before-reveal loop over SEED (see seed.js).
 * All data access goes through getPlaces()/getPlace() so swapping in a real
 * backend is a one-function change.
 */

// --- data access (swap these two for fetch() when the backend is live) ---
const getPlaces = () => SEED.places;
const getPlace = (id) => SEED.places.find((p) => p.id === id);

// honor the OS "reduce motion" setting (a11y — ui-ux-pro-max §7)
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// --- view routing ---
const views = {
  places: document.getElementById("view-places"),
  reconstruct: document.getElementById("view-reconstruct"),
  reveal: document.getElementById("view-reveal"),
};
function show(name) {
  Object.values(views).forEach((v) => v.classList.remove("active"));
  views[name].classList.add("active");
}

let active = null; // currently opened place

// --- 1. place list (stands in for geofence triggers) ---
function renderPlaces() {
  const list = document.getElementById("place-list");
  list.innerHTML = "";
  getPlaces().forEach((p) => {
    const el = document.createElement("div");
    el.className = "place";
    // keyboard-accessible: focusable + Enter/Space activate (a11y — §1/§2)
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", `Return to ${p.name}`);
    el.innerHTML = `
      <div class="thumb" style="background:${p.anchor.photo}">${p.icon}</div>
      <div class="pmeta">
        <div class="pname">${p.name}</div>
        <div class="pdesc">${p.desc}</div>
      </div>
      <span class="pback">${p.back}</span>`;
    el.addEventListener("click", () => openPlace(p.id));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPlace(p.id); }
    });
    list.appendChild(el);
  });
}

// --- 2. reconstruct-before-reveal ---
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
    // no staged animation — show everything at once
    active.cues.forEach((c) => {
      const el = document.createElement("div");
      el.className = "cue";
      el.style.animation = "none";
      el.style.opacity = "1";
      el.innerHTML = cueHTML(c);
      feed.appendChild(el);
    });
    revealBtn.classList.remove("hidden");
    return;
  }

  // stage cues in one at a time — the "reconstruction" beat
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

// --- 3. grounded storyline + talk-to-past-you ---
function reveal() {
  // build storyline with inline citation superscripts
  const storyEl = document.getElementById("storyline");
  let html = active.storyline.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  html = html.replace(/\{(\d+)\}/g, (_, i) => {
    const cite = active.citations[Number(i)];
    return `<sup class="cited" title="${cite ? cite.label : ""}">[${cite ? cite.n : "?"}]</sup>`;
  });
  storyEl.innerHTML = html;

  const cites = document.getElementById("citations");
  cites.innerHTML = active.citations
    .map((c) => `<span class="chip"><b>[${c.n}]</b> ${c.label}</span>`)
    .join("");

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
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
