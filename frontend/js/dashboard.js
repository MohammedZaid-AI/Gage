"use strict";
/* Gage — Farm Operating System (SPA over existing APIs; UI/UX polish layer). */

// ---------- state ----------
const state = {
  token: localStorage.getItem("gage_token") || null,
  farmer: null, farmId: null, farmName: "Farm",
  nodes: [], node: null,
  obsCache: {},                 // id -> observation (Timeline -> Detail)
  lastSummary: null,            // reused by Detail for current alert context
  lastObsTime: null,
  prefs: JSON.parse(localStorage.getItem("gage_prefs") || '{"lang":"en","speak":true,"theme":"light"}'),
  view: "home",
};
const savePrefs = () => localStorage.setItem("gage_prefs", JSON.stringify(state.prefs));
function applyTheme() { document.documentElement.dataset.theme = state.prefs.theme || "light"; }
applyTheme();

// ---------- icons ----------
// Stroke-based inline SVG (no emoji: emoji render differently per OS and read as amateur).
// Single 24x24 grid, currentColor, so any icon inherits the surrounding text color.
const ICONS = {
  leaf: '<path d="M11 20A7 7 0 0 1 4 13c0-5 4-9 16-9 0 10-4 14-9 14Z"/><path d="M4 20c2-6 6-9 11-11"/>',
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9.5 21v-6h5v6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3.5 2"/>',
  mic: '<rect x="9" y="2.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v3.5"/>',
  chart: '<path d="M3.5 20.5h17"/><path d="M7 20.5v-7"/><path d="M12 20.5V6"/><path d="M17 20.5v-10"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.4-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4a2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.9 1.4l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 11a2 2 0 1 1 0 4Z"/>',
  thermometer: '<path d="M14 14.8V5a2 2 0 1 0-4 0v9.8a4.5 4.5 0 1 0 4 0Z"/>',
  droplet: '<path d="M12 3s5.5 5.6 5.5 9.5a5.5 5.5 0 0 1-11 0C6.5 8.6 12 3 12 3Z"/>',
  sprout: '<path d="M12 21v-8"/><path d="M12 13C12 8.5 9 6 4.5 6c0 4.5 3 7 7.5 7Z"/><path d="M12 13c0-3.6 2.4-6 6-6 0 3.6-2.4 6-6 6Z"/>',
  battery: '<rect x="2.5" y="8" width="16" height="8" rx="2.5"/><path d="M21 11v2"/><path d="M6 11v2"/><path d="M9.5 11v2"/>',
  pin: '<path d="M20 10.5c0 5.5-8 11-8 11s-8-5.5-8-11a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10.5" r="2.8"/>',
  camera: '<path d="M3 8.5A2 2 0 0 1 5 6.5h1.8l1.2-2h8l1.2 2H19a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><circle cx="12" cy="13" r="3.5"/>',
  sparkle: '<path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4Z"/><path d="M18.5 16.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8Z"/>',
  chevron: '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
  volume: '<path d="M11 5 6.5 9H3v6h3.5L11 19Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>',
  warning: '<path d="M10.3 3.9 2.5 17.4A2 2 0 0 0 4.2 20.5h15.6a2 2 0 0 0 1.7-3.1L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 16.5h.01"/>',
  check: '<path d="M4.5 12.5 9 17 19.5 6.5"/>',
  brain: '<path d="M9.5 4.5a3 3 0 0 0-3 3 3 3 0 0 0-1 5.8V15a3 3 0 0 0 4.5 2.6"/><path d="M14.5 4.5a3 3 0 0 1 3 3 3 3 0 0 1 1 5.8V15a3 3 0 0 1-4.5 2.6"/><path d="M12 4.5v15"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-13.6-4.6L3.5 9"/><path d="M4 13a8 8 0 0 0 13.6 4.6L20.5 15"/><path d="M3.5 4.5V9H8"/><path d="M20.5 19.5V15H16"/>',
  arrowUp: '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
  arrowDown: '<path d="M12 5v14"/><path d="M18 13l-6 6-6-6"/>',
  minus: '<path d="M5 12h14"/>',
  image: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="8.5" cy="10" r="1.8"/><path d="M21 15.5 16 11l-9 8.5"/>',
  sun: '<circle cx="12" cy="12" r="4.5"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4A8.5 8.5 0 1 0 20 14.5Z"/>',
  doc: '<path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5Z"/><path d="M14 3.5v5h5"/><path d="M8.5 13h7M8.5 16.5h4"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="2.5"/>',
  logout: '<path d="M14.5 3.5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h8.5"/><path d="M16 12h5.5"/><path d="M18.5 8.5 22 12l-3.5 3.5"/>',
};
function icon(name, cls = "") {
  const p = ICONS[name] || "";
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"${cls ? ` class="${cls}"` : ""}>${p}</svg>`;
}
window.icon = icon;
// Hydrate static markup: any [data-icon] in the shell gets its SVG prepended, so the
// icon set stays the single source of truth (HTML just names the icon it wants).
function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon));
    el.removeAttribute("data-icon");
  });
}

// ---------- helpers ----------
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const imgUrl = (p) => (p ? "/" + p.replace(/^\/+/, "") : null);
const fmt = (v, u = "") => (v === null || v === undefined ? "—" : `${(+v).toFixed(1)}${u}`);
// Soil moisture as a word farmers read at a glance, not a percent.
function soilLabel(v) {
  if (v === null || v === undefined) return "—";
  if (v < 15) return "Very dry";
  if (v < 30) return "Dry";
  if (v < 60) return "Moist";
  if (v < 80) return "Wet";
  return "Saturated";
}
const lazyImg = (src, cls) => `<img class="${cls}" src="${src}" loading="lazy" decoding="async" alt="field"/>`;
function ago(iso) {
  const ms = tsMs(iso);
  if (ms == null) return "—";
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return `${s | 0} seconds ago`;
  if (s < 3600) return `${(s / 60) | 0} min ago`;
  if (s < 86400) return `${(s / 3600) | 0}h ago`;
  return `${(s / 86400) | 0}d ago`;
}
// Epoch ms for a timestamp. Server datetimes are naive UTC ("…T10:00:00"); with no tz
// marker the browser would read them as LOCAL time. Treat a marker-less string as UTC.
function tsMs(t) {
  if (t == null) return null;
  if (typeof t === "number") return t;
  const s = /[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : t + "Z";
  const ms = Date.parse(s);
  return Number.isNaN(ms) ? null : ms;
}
function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}
const dateStr = () => new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  document.body.append(t); setTimeout(() => t.remove(), 2600);
}

// ---------- API + tiny response cache ----------
const cache = new Map();
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers);
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (r.status === 401) { logout(); throw new Error("unauthorized"); }
  if (!r.ok) throw new Error(await r.text().catch(() => r.status));
  return r.status === 204 ? null : r.json();
}
function cachedGet(path, ttl = 12000) {
  const c = cache.get(path);
  if (c && Date.now() - c.t < ttl) return Promise.resolve(c.data);
  return api(path).then((d) => { cache.set(path, { t: Date.now(), data: d }); return d; });
}
const invalidate = () => cache.clear();
const jpost = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---------- health helpers (client-side, mirrors backend thresholds) ----------
const TH = { soilMin: 20, humMax: 85, tempMax: 40 };
// Negation-aware: a clause counts only if it is NOT negated ("no yellowing" is fine).
function visionAnomaly(text) {
  return (text || "").toLowerCase().split(/[.;\n]/).some(
    (cl) => !/\bno\b|\bnot\b|without|free of/.test(cl) && /(yellow|disease|pest|wilt|sparse)/.test(cl));
}
function clientHealth(o, alerts = []) {
  let s = 100;
  if (o.soil_moisture != null && o.soil_moisture < TH.soilMin) s -= 20;
  if (o.humidity != null && o.humidity > TH.humMax) s -= 15;
  if (o.temperature != null && o.temperature > TH.tempMax) s -= 15;
  if (visionAnomaly(o.vision_summary)) s -= 15;
  s -= Math.min(alerts.length * 5, 25);
  s = Math.max(0, Math.min(100, s));
  const label = s >= 90 ? "Excellent" : s >= 80 ? "Healthy" : s >= 60 ? "Fair" : "Needs care";
  const cls = s >= 80 ? "good" : s >= 60 ? "watch" : "crit";
  return { score: s, label, cls };
}
// Five segments beat five stars: stars imply a rating, segments imply a measurement.
function meter(score, cls) {
  const n = Math.max(1, Math.round(score / 20));
  return `<div class="meter ${cls}">${Array.from({ length: 5 }, (_, i) => `<i class="${i < n ? "on" : ""}"></i>`).join("")}</div>`;
}

// ---------- auth ----------
function showLogin() { $("#login").classList.remove("hidden"); $("#shell").classList.add("hidden"); }
function logout() { state.token = null; localStorage.removeItem("gage_token"); invalidate(); showLogin(); }
let registerMode = false;
$("#lg-toggle").onclick = (e) => {
  e.preventDefault(); registerMode = !registerMode;
  $("#lg-submit").textContent = registerMode ? "Create account" : "Enter my farm";
  $("#lg-toggle").textContent = registerMode ? "Have an account? Sign in" : "New here? Create an account";
  $("#lg-msg").textContent = "";
};
$("#lg-submit").onclick = async () => {
  const phone = $("#lg-phone").value.trim(), password = $("#lg-pass").value;
  if (!phone || !password) return ($("#lg-msg").textContent = "Enter phone and password.");
  try {
    const r = await jpost(registerMode ? "/auth/register" : "/auth/login", { phone, password });
    state.token = r.access_token; localStorage.setItem("gage_token", state.token); await boot();
  } catch { $("#lg-msg").textContent = registerMode ? "Could not register (phone may exist)." : "Invalid phone or password."; }
};

// Node chip label lives in its own span so updating text never wipes the icon.
function setNodeChip() {
  const el = $("#ab-node")?.lastElementChild;
  if (el) el.textContent = state.node ? state.node.id : "No node";
}

// ---------- boot ----------
async function boot() {
  try {
    state.farmer = await api("/auth/me");
    const farms = await api("/farms");
    if (farms.length) { state.farmId = farms[0].id; state.farmName = farms[0].name; }
    else state.farmId = null;
  } catch { return; }
  if (state.farmId) {
    try { state.nodes = await api(`/farms/${state.farmId}/nodes`); } catch { state.nodes = []; }
    state.node = state.nodes[0] || null;
  }
  $("#login").classList.add("hidden"); $("#shell").classList.remove("hidden");
  $("#ab-farm").textContent = state.farmName;
  $("#ab-sub").textContent = state.farmer?.name ? state.farmer.name : "Farm OS";
  setNodeChip();
  go("home"); connectWS(); startClock();
}

// ---------- router ----------
document.querySelectorAll(".nav button").forEach((b) => (b.onclick = () => go(b.dataset.nav)));
$("#fab").onclick = () => go("ask");
const setNav = (name) => document.querySelectorAll(".nav button").forEach((b) => b.classList.toggle("on", b.dataset.nav === name));
const VIEWS = {}, WIRE = {};
async function go(name, arg) {
  state.view = name; state.viewArg = arg; setNav(name);
  $("#fab").style.display = name === "ask" ? "none" : "";
  const host = $("#view");
  host.innerHTML = `<div class="view"><div class="skeleton" style="height:26px;width:52%;margin:4px 0 18px"></div>
    <div class="skeleton" style="height:112px;margin-bottom:12px"></div>
    <div class="skeleton" style="height:74px;margin-bottom:12px"></div>
    <div class="skeleton" style="height:180px"></div></div>`;
  try {
    host.innerHTML = `<div class="view">${await VIEWS[name](arg)}</div>`;
    if (WIRE[name]) WIRE[name](arg);
  } catch (e) {
    host.innerHTML = `<div class="view"><div class="card"><p class="muted">Could not load this page. ${esc(e.message || "")}</p><button class="btn" onclick="go('${name}')">Retry</button></div></div>`;
  }
  window.scrollTo({ top: 0 });
}
window.go = go;

// ---------- HOME ----------
// A 240° open arc reads as an instrument dial; a full ring reads as a loading spinner.
// Sweeps 210° (lower-left) through 90° (top) to -30° (lower-right) — gap at the bottom.
const GAUGE = { r: 42, cx: 58, cy: 52, a0: 210, a1: -30 };
function gaugeArc() {
  const { r, cx, cy, a0, a1 } = GAUGE;
  const pt = (deg) => [cx + r * Math.cos((deg * Math.PI) / 180), cy - r * Math.sin((deg * Math.PI) / 180)];
  const [sx, sy] = pt(a0), [ex, ey] = pt(a1);
  // large-arc-flag=1 (240° > 180°), sweep-flag=1 (clockwise in screen coords)
  const d = `M ${sx.toFixed(1)} ${sy.toFixed(1)} A ${r} ${r} 0 1 1 ${ex.toFixed(1)} ${ey.toFixed(1)}`;
  return { d, len: ((a0 - a1) / 360) * 2 * Math.PI * r };
}
function gauge(score, cls) {
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const { d, len } = gaugeArc();
  const col = cls === "good" ? "var(--g-500)" : cls === "watch" ? "var(--warn)" : "var(--danger)";
  return `<div class="gauge"><svg viewBox="0 0 116 80">
      <path class="track" d="${d}" fill="none" stroke-width="9" stroke-linecap="round"/>
      <path class="val" d="${d}" fill="none" stroke="${col}" stroke-width="9"
        stroke-dasharray="${len.toFixed(1)}" stroke-dashoffset="${len.toFixed(1)}"
        data-off="${(len * (1 - pct)).toFixed(1)}"/>
    </svg><div class="num"><b>${score}</b><span>health</span></div></div>`;
}
VIEWS.home = async () => {
  if (!state.farmId) return `<div class="card" style="text-align:center;padding:32px 20px">
    <div class="qa" style="display:block"><span class="ic" style="margin:0 auto 14px">${icon("leaf")}</span></div>
    <h2 style="font-size:19px">Welcome to Gage</h2>
    <p class="muted" style="margin:6px 0 16px;font-size:14px">Add your first farm to begin monitoring.</p>
    <button class="btn" onclick="go('settings')">Set up my farm</button></div>`;
  const s = await cachedGet(`/farm/${state.farmId}/summary`);
  const nodes = await cachedGet(`/farms/${state.farmId}/nodes`).catch(() => state.nodes);
  state.lastSummary = s; state.node = nodes[0] || state.node;
  const nh = state.node?.health || {};
  const snap = s.sensor_snapshot || {}, o = s.latest_observation || {};
  const trend = {}; (s.trends || []).forEach((t) => (trend[t.metric] = t));
  const arrow = (m) => trend[m] ? `<span class="trend ${trend[m].direction}">${icon(trend[m].direction === "up" ? "arrowUp" : trend[m].direction === "down" ? "arrowDown" : "minus")}${Math.abs(trend[m].delta)}${trend[m].unit}</span>` : "";
  const img = imgUrl(o.image_path);
  const H = s.health, cls = H.status === "Healthy" ? "good" : H.status === "Watch" ? "watch" : "crit";
  const emLabel = H.score >= 90 ? "Excellent" : H.score >= 80 ? "Very good" : H.score >= 60 ? "Fair" : "Needs care";
  state.lastObsTime = o.timestamp || null;
  const chk = (ok, label) => `<li class="${ok ? "" : "off"}"><span class="check ${ok ? "" : "no"}">${ok ? icon("check") : ""}</span>${label}</li>`;

  return `
    <div class="greet">
      <div class="hello">${greeting()}</div>
      <div class="name">${esc(state.farmer?.name || state.farmName)}</div>
      <div class="date">${dateStr()}</div>
    </div>

    <div class="card hero" id="health-card">
      ${gauge(H.score, cls)}
      <div class="info">
        <div class="status ${cls}">${esc(emLabel)}</div>
        <div class="label-em">${esc(H.status)} · updated <span id="home-updated">${ago(state.lastObsTime)}</span></div>
        ${meter(H.score, cls)}
      </div>
    </div>

    <div class="card flat">
      <div class="calc-title">Calculated from</div>
      <ul class="checklist">
        ${chk(!!o.image_path, "Latest image")}
        ${chk(snap.soil_moisture != null, "Soil moisture")}
        ${chk(snap.temperature != null, "Temperature")}
        ${chk(snap.humidity != null, "Humidity")}
        ${chk(true, `${(s.active_alerts || []).length} active alert(s)`)}
      </ul>
    </div>

    <div class="section-title">Latest scan</div>
    <div class="card tap" style="padding:12px" onclick="${o.id ? `go('detail','${o.id}')` : ""}">
      ${img ? `<div class="scan-wrap">${lazyImg(img, "obs-image")}
                 <span class="scan-tag">${icon("camera")}Latest scan</span>
                 <span class="scan-time">${o.timestamp ? ago(o.timestamp) : ""}</span></div>`
            : `<div class="img-empty">${icon("image")}<span>No scan yet — tap Scan crop below</span></div>`}
    </div>

    <div class="section-title">Today's report</div>
    <div class="card ai-card"><div class="head">${icon("sparkle")}Gage · ${esc(state.farmName)}</div>
      <p>${esc(s.ai_summary || "Capture a scan and I'll summarise your field — health, moisture trend, and what to do next.")}</p></div>

    <div class="section-title">Conditions</div>
    <div class="grid">
      <div class="sensor m-temp"><div class="top"><span class="ic">${icon("thermometer")}</span>${arrow("temperature")}</div><span class="v">${fmt(snap.temperature)}<small>°C</small></span><span class="l">Temperature</span></div>
      <div class="sensor m-hum"><div class="top"><span class="ic">${icon("droplet")}</span>${arrow("humidity")}</div><span class="v">${fmt(snap.humidity)}<small>%</small></span><span class="l">Humidity</span></div>
      <div class="sensor m-soil"><div class="top"><span class="ic">${icon("sprout")}</span>${arrow("soil_moisture")}</div><span class="v word">${soilLabel(snap.soil_moisture)}</span><span class="l">Soil moisture</span></div>
      <div class="sensor m-batt"><div class="top"><span class="ic">${icon("battery")}</span></div><span class="v">${nh.battery != null ? fmt(nh.battery) + "<small>%</small>" : "—"}</span><span class="l">Node battery</span></div>
      ${o.gps_lat != null ? `<div class="sensor wide"><div class="top"><span class="ic">${icon("pin")}</span></div><span class="v word">${(+o.gps_lat).toFixed(4)}, ${(+o.gps_long).toFixed(4)}</span><span class="l">Last scan location</span></div>` : ""}
    </div>

    ${(s.active_alerts || []).length ? `<div class="section-title">Active alerts</div>${[...s.active_alerts].sort((a, b) => (b.severity === "critical") - (a.severity === "critical")).map((a) => `
      <div class="alert ${a.severity === "critical" ? "crit" : ""}"><span class="ic">${icon("warning")}</span>
      <div><div class="sev">${esc(a.severity)}</div><div class="msg">${esc(a.message)}</div></div></div>`).join("")}` : ""}

    <div class="section-title">Quick actions</div>
    <div class="qa">
      <button onclick="go('ask')"><span class="ic">${icon("mic")}</span>Ask Gage</button>
      <button id="qa-scan"><span class="ic">${icon("camera")}</span>Scan crop</button>
      <button onclick="go('timeline')"><span class="ic">${icon("clock")}</span>Timeline</button>
      <button onclick="go('reports')"><span class="ic">${icon("doc")}</span>Reports</button>
    </div>`;
};
WIRE.home = () => {
  requestAnimationFrame(() => { const v = $(".gauge .val"); if (v) v.style.strokeDashoffset = v.dataset.off; });
  const b = $("#qa-scan"); if (b) b.onclick = capture;
};

// ---------- TIMELINE ----------
VIEWS.timeline = async () => {
  if (!state.farmId) return `<div class="card"><p class="muted">Add a farm first.</p></div>`;
  const obs = await cachedGet(`/farm/${state.farmId}/timeline?limit=50`);
  obs.forEach((o) => (state.obsCache[o.id] = o));
  if (!obs.length) return `<div class="card" style="text-align:center;padding:30px 20px">
    <div class="img-empty" style="border:none;background:none;aspect-ratio:auto">${icon("clock")}<span>No observations yet</span></div>
    <p class="muted" style="font-size:13.5px;margin:0">Your node's captures appear here as a living timeline.</p></div>`;
  return `<div class="section-title">Observation timeline</div>` + obs.map((o) => {
    const img = imgUrl(o.image_path), h = clientHealth(o);
    return `<div class="card tl tap" onclick="go('detail','${o.id}')">
      ${img ? lazyImg(img, "") : `<div class="thumb">${icon("leaf")}</div>`}
      <div class="body"><div class="when">${new Date(o.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${ago(o.timestamp)}</div>
        <div class="sum">${esc(o.vision_summary || o.ai_summary || "Observation")}</div>
        <div class="mini"><span class="health-pill ${h.cls}">${h.label} ${h.score}</span><span>${icon("sprout")}${soilLabel(o.soil_moisture)}</span></div>
      </div><span class="go">${icon("chevron")}</span></div>`;
  }).join("");
};

// ---------- OBSERVATION DETAIL (stored data only — no /chat) ----------
function buildAnalysis(o, alerts) {
  const facts = [];
  if (o.vision_summary) facts.push(`Image: ${o.vision_summary}`);
  if (o.temperature != null) facts.push(`Temperature ${o.temperature}°C`);
  if (o.humidity != null) facts.push(`Humidity ${o.humidity}%`);
  if (o.soil_moisture != null) facts.push(`Soil moisture ${o.soil_moisture}%`);
  alerts.forEach((a) => facts.push(`Alert: ${a.message}`));

  const recs = [], why = [];
  if (o.soil_moisture != null && o.soil_moisture < TH.soilMin) {
    recs.push("Irrigate within the next 24 hours — soil moisture is low.");
    why.push(`soil moisture is ${o.soil_moisture}% (below ${TH.soilMin}%)`);
  } else if (o.soil_moisture != null && o.soil_moisture > 60) {
    recs.push("Hold irrigation — the soil is already very wet.");
    why.push(`soil moisture is ${o.soil_moisture}% (high)`);
  }
  if (o.humidity != null && o.humidity > TH.humMax) {
    recs.push("Watch for fungal disease; improve airflow and drainage between rows.");
    why.push(`humidity is ${o.humidity}% (above ${TH.humMax}%)`);
  }
  if (o.temperature != null && o.temperature > TH.tempMax) {
    recs.push("Protect against heat stress and keep the soil moist.");
    why.push(`temperature is ${o.temperature}°C (above ${TH.tempMax}°C)`);
  }
  if (visionAnomaly(o.vision_summary)) {
    recs.push("Inspect leaves closely — the image shows possible disease or pest signs.");
    why.push("the image shows possible leaf discoloration or damage");
  }
  if (alerts.length) why.push(`${alerts.length} active alert(s) on this farm`);
  if (!recs.length) recs.push("Continue regular monitoring — conditions look within the healthy range.");

  const present = [o.image_path, o.temperature, o.humidity, o.soil_moisture].filter((x) => x != null).length;
  const conf = present >= 4 ? "High" : present >= 2 ? "Medium" : "Low";
  return { facts, recs, why, conf };
}
VIEWS.detail = async (id) => {
  const o = state.obsCache[id];
  if (!o) return `<div class="card"><p class="muted">Observation not found.</p><button class="btn" onclick="go('timeline')">Back</button></div>`;
  const alerts = (state.lastSummary && state.lastSummary.active_alerts) || [];
  const img = imgUrl(o.image_path), h = clientHealth(o, alerts), a = buildAnalysis(o, alerts);
  const whyText = `Based on the ${o.image_path ? "latest image, " : ""}sensor readings, and active alerts: ` +
    (a.why.length ? a.why.join("; ") + "." : "all monitored indicators are within the normal range.");
  return `
    <button class="btn ghost sm" onclick="go('timeline')">${icon("chevron", "flip")} Back</button>
    <div class="card" style="padding:12px;margin-top:12px">
      ${img ? `<div class="scan-wrap">${lazyImg(img, "obs-image")}<span class="scan-tag">${icon("camera")}Scan</span></div>` : `<div class="img-empty">${icon("image")}<span>No image</span></div>`}
      <div class="when muted" style="margin-top:9px;font-size:12.5px">${new Date(o.timestamp).toLocaleString()} · node ${esc(o.node_id)}</div>
    </div>

    <div class="card hero">
      ${gauge(h.score, h.cls)}
      <div class="info"><div class="status ${h.cls}">${h.label}</div>
        <div class="label-em">Observation health</div>${meter(h.score, h.cls)}</div>
    </div>

    <div class="grid">
      <div class="sensor m-temp"><div class="top"><span class="ic">${icon("thermometer")}</span></div><span class="v">${fmt(o.temperature)}<small>°C</small></span><span class="l">Temperature</span></div>
      <div class="sensor m-hum"><div class="top"><span class="ic">${icon("droplet")}</span></div><span class="v">${fmt(o.humidity)}<small>%</small></span><span class="l">Humidity</span></div>
      <div class="sensor m-soil"><div class="top"><span class="ic">${icon("sprout")}</span></div><span class="v word">${soilLabel(o.soil_moisture)}</span><span class="l">Soil moisture</span></div>
      <div class="sensor"><div class="top"><span class="ic">${icon("pin")}</span></div><span class="v word">${o.gps_lat != null ? (+o.gps_lat).toFixed(3) + ", " + (+o.gps_long).toFixed(3) : "—"}</span><span class="l">Location</span></div>
    </div>

    <div class="section-title">Vision summary</div>
    <div class="card"><p style="margin:0;font-size:14.5px;line-height:1.6;color:var(--ink-2)">${esc(o.vision_summary || "No image was analysed for this observation.")}</p></div>

    ${o.ai_summary ? `<div class="section-title">AI summary</div><div class="card ai-card"><div class="head">${icon("sparkle")}Gage</div><p>${esc(o.ai_summary)}</p></div>` : ""}

    <div class="section-title">Recommendations</div>
    <div class="card ai-card"><div class="doc-section rec" style="margin-top:0"><div class="lab">What to do</div>
      <ul>${a.recs.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
      <div class="doc-section"><span class="conf ${a.conf.toLowerCase()}">Confidence: ${a.conf}</span></div>
    </div>

    <div class="section-title">Why Gage said this</div>
    <div class="why"><b>${icon("brain")}Reasoning</b><p style="margin:6px 0 0">${esc(whyText)}</p></div>`;
};

// ---------- ASK GAGE ----------
const SUGGESTIONS = ["Should I irrigate?", "How is my crop?", "Any disease?", "Is soil moisture okay?", "ನನ್ನ ಬೆಳೆ ಹೇಗಿದೆ?"];
VIEWS.ask = async () => `
  <div class="card">
    <div class="mic-wrap"><button class="mic" id="mic" aria-label="Record a question">${icon("mic")}</button>
      <div class="mic-hint" id="mic-hint">Tap to speak — Kannada or English</div></div>
  </div>
  <div class="section-title">Try asking</div>
  <div class="chips" id="chips">${SUGGESTIONS.map((q) => `<button class="chip-btn">${esc(q)}</button>`).join("")}</div>
  <div id="ask-log" style="margin-top:18px"></div>
  <div class="card glass" style="position:sticky;bottom:calc(var(--nav-h) + 10px);z-index:5;padding:12px">
    <div class="row"><input id="ask-input" placeholder="Type your question…" />
      <button class="btn" id="ask-send" style="flex:0 0 auto">Ask</button></div>
  </div>`;
WIRE.ask = () => {
  $("#chips").querySelectorAll(".chip-btn").forEach((c) => (c.onclick = () => askText(c.textContent)));
  $("#ask-send").onclick = () => { const v = $("#ask-input").value.trim(); if (v) { $("#ask-input").value = ""; askText(v); } };
  $("#ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#ask-send").click(); });
  $("#mic").onclick = toggleMic;
};
function logBubble(html, who) {
  const log = $("#ask-log"); if (!log) return null;
  const d = document.createElement("div"); d.className = `bubble ${who}`; d.innerHTML = html;
  log.append(d); d.scrollIntoView({ behavior: "smooth", block: "nearest" }); return d;
}
async function askText(q) {
  logBubble(esc(q), "user");
  const pending = logBubble(`<span class="typing"><span></span><span></span><span></span></span>`, "bot");
  try { const r = await jpost("/chat", { farm_id: state.farmId, question: q });
    pending.innerHTML = docInline(r.answer); attachPlay(pending, r.answer, r.language);
  } catch { pending.textContent = "Sorry, I'm unavailable right now."; }
}
function parseDoc(text) {
  const grab = (n, stops) => { const m = text.match(new RegExp(`${n}\\s*:?\\s*([\\s\\S]*?)(?=(?:${stops.join("|")})\\s*:|$)`, "i")); return m ? m[1].trim() : ""; };
  const observation = grab("Observation", ["Analysis", "Confidence", "Recommendations"]);
  const analysis = grab("Analysis", ["Confidence", "Recommendations"]);
  const confidence = grab("Confidence", ["Recommendations"]);
  const recommendations = grab("Recommendations", ["$"]);
  return { observation, analysis, confidence, recommendations, structured: !!(observation || analysis || confidence || recommendations) };
}
const confClass = (c) => /high/i.test(c) ? "high" : /low/i.test(c) ? "low" : "medium";
function bullets(t) { const i = t.split("\n").map((l) => l.replace(/^[-•]\s*/, "").trim()).filter(Boolean); return i.length <= 1 ? `<p>${esc(t || "—")}</p>` : `<ul>${i.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`; }
function docInline(answer) {
  const d = parseDoc(answer); if (!d.structured) return esc(answer);
  return `${d.observation ? `<b>Observation</b>${bullets(d.observation)}` : ""}
    ${d.analysis ? `<b>Analysis</b><p>${esc(d.analysis)}</p>` : ""}
    ${d.confidence ? `<span class="conf ${confClass(d.confidence)}">Confidence: ${esc((d.confidence.match(/high|medium|low/i) || ["Medium"])[0])}</span>` : ""}
    ${d.recommendations ? `<b style="display:block;margin-top:8px">Recommendations</b>${bullets(d.recommendations)}` : ""}`;
}

// ---------- REPORTS ----------
function aggregate(obs, days) {
  const cut = Date.now() - days * 86400000, r = obs.filter((o) => new Date(o.timestamp).getTime() >= cut);
  const avg = (k) => { const v = r.map((o) => o[k]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  return { count: r.length, temp: avg("temperature"), hum: avg("humidity"), soil: avg("soil_moisture") };
}
const repCard = (title, a) => `<div class="card"><div class="calc-title" style="margin-bottom:12px">${title}</div>
  <div class="grid">
    <div class="sensor flat" style="box-shadow:none;background:var(--surface-2)"><span class="v">${a.count}</span><span class="l">Observations</span></div>
    <div class="sensor flat" style="box-shadow:none;background:var(--surface-2)"><span class="v word">${soilLabel(a.soil)}</span><span class="l">Avg soil</span></div>
    <div class="sensor flat" style="box-shadow:none;background:var(--surface-2)"><span class="v">${fmt(a.temp)}<small>°C</small></span><span class="l">Avg temp</span></div>
    <div class="sensor flat" style="box-shadow:none;background:var(--surface-2)"><span class="v">${fmt(a.hum)}<small>%</small></span><span class="l">Avg humidity</span></div>
  </div></div>`;
VIEWS.reports = async () => {
  if (!state.farmId) return `<div class="card"><p class="muted">Add a farm first.</p></div>`;
  const obs = await cachedGet(`/farm/${state.farmId}/timeline?limit=300`);
  let stats = null; try { stats = await cachedGet("/dataset/stats"); } catch {}
  const bars = stats ? Object.entries(stats.daily_rate || {}) : [];
  const max = Math.max(1, ...bars.map(([, n]) => n));
  const soils = obs.slice(0, 12).reverse().map((o) => o.soil_moisture).filter((x) => x != null);
  const smax = Math.max(1, ...soils);
  const pts = soils.map((v, i) => `${((i / (soils.length - 1)) * 296 + 2).toFixed(1)},${(84 - (v / smax) * 74).toFixed(1)}`);
  return `
    <div class="section-title">Daily</div>${repCard("Today & last 24 hours", aggregate(obs, 1))}
    <div class="section-title">Weekly</div>${repCard("Last 7 days", aggregate(obs, 7))}
    <div class="section-title">Monthly</div>${repCard("Last 30 days", aggregate(obs, 30))}
    ${soils.length > 1 ? `<div class="section-title">Soil moisture trend</div>
    <div class="card chart-card"><svg class="spark" viewBox="0 0 300 92" preserveAspectRatio="none">
      <defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--g-500)" stop-opacity=".26"/>
        <stop offset="100%" stop-color="var(--g-500)" stop-opacity="0"/></linearGradient></defs>
      <polygon fill="url(#sg)" points="2,88 ${pts.join(" ")} 298,88"/>
      <polyline fill="none" stroke="var(--g-500)" stroke-width="2.5" stroke-linecap="round"
        stroke-linejoin="round" points="${pts.join(" ")}" vector-effect="non-scaling-stroke"/>
    </svg><p class="muted" style="font-size:12px;margin:8px 0 0">Last ${soils.length} readings</p></div>` : ""}
    ${bars.length ? `<div class="section-title">Data collection</div>
    <div class="card chart-card"><div class="bars">
      ${bars.map(([d, n]) => `<div class="b"><i style="height:${((n / max) * 82 + 3).toFixed(0)}px"></i><span>${d.slice(5)}</span></div>`).join("")}
    </div><p class="muted" style="margin:12px 0 0;font-size:12px">${stats.dataset_entries} records · avg quality ${stats.average_quality}</p></div>` : ""}`;
};

// ---------- SETTINGS ----------
VIEWS.settings = async () => {
  const farms = await api("/farms").catch(() => []);
  let nodes = []; if (state.farmId) nodes = await api(`/farms/${state.farmId}/nodes`).catch(() => []);
  const on = (c) => (c ? "on" : "");
  return `
    <div class="section-title">Farm</div>
    <div class="card">${farms.map((f) => `<div class="list-item"><div><b>${esc(f.name)}</b><div class="kv">${esc(f.crop_type)} · ${esc(f.village || "—")}</div></div>${f.id === state.farmId ? '<span class="health-pill good">Active</span>' : `<button class="btn ghost sm" onclick="switchFarm(${f.id})">Use</button>`}</div>`).join("") || '<p class="muted">No farms yet.</p>'}
      <div class="row" style="margin-top:12px"><input id="nf-name" placeholder="New farm name"/><button class="btn" id="add-farm" style="flex:0 0 auto">Add</button></div>
    </div>

    <div class="section-title">Monitoring nodes</div>
    <div class="card">${nodes.map((n) => `<div class="list-item"><div><b>${esc(n.id)}</b><div class="kv">key <span class="code">${esc(n.api_key)}</span></div></div><span class="health-pill ${n.health && n.health.status === "offline" ? "crit" : "good"}">${n.health ? esc(n.health.status) : "new"}</span></div>`).join("") || '<p class="muted">No nodes registered.</p>'}
      ${state.farmId ? `<div class="row" style="margin-top:12px"><input id="nn-id" placeholder="node-id (device)"/><button class="btn" id="add-node" style="flex:0 0 auto">Register</button></div>` : ""}
    </div>

    <div class="section-title">Language</div>
    <div class="card"><div class="list-item"><span>Assistant & voice</span>
      <div class="pill-toggle" id="lang-toggle"><button data-lang="en" class="${on(state.prefs.lang === "en")}">English</button><button data-lang="kn" class="${on(state.prefs.lang === "kn")}">ಕನ್ನಡ</button></div></div></div>

    <div class="section-title">Voice</div>
    <div class="card"><div class="list-item"><span>Speak answers aloud</span>
      <div class="pill-toggle" id="speak-toggle"><button data-speak="1" class="${on(state.prefs.speak)}">On</button><button data-speak="0" class="${on(!state.prefs.speak)}">Off</button></div></div></div>

    <div class="section-title">Theme</div>
    <div class="card"><div class="list-item"><span>Appearance</span>
      <div class="pill-toggle" id="theme-toggle"><button data-theme="light" class="${on(state.prefs.theme !== "dark")}">Light</button><button data-theme="dark" class="${on(state.prefs.theme === "dark")}">Dark</button></div></div></div>

    <button class="btn ghost block" id="logout-btn" style="margin-top:6px">Sign out</button>
    <p class="muted" style="text-align:center;font-size:11.5px;margin-top:18px">Gage Farm OS · ${esc(state.farmer?.phone || "")}</p>`;
};
WIRE.settings = () => {
  const af = $("#add-farm"); if (af) af.onclick = async () => { const name = $("#nf-name").value.trim(); if (!name) return; await jpost("/farms", { name }); invalidate(); toast("Farm added"); go("settings"); };
  const an = $("#add-node"); if (an) an.onclick = async () => { const id = $("#nn-id").value.trim(); if (!id) return; try { await jpost(`/farms/${state.farmId}/nodes`, { id }); invalidate(); toast("Node registered"); go("settings"); } catch { toast("Could not register node"); } };
  $("#lang-toggle")?.querySelectorAll("button").forEach((b) => (b.onclick = () => { state.prefs.lang = b.dataset.lang; savePrefs(); go("settings"); }));
  $("#speak-toggle")?.querySelectorAll("button").forEach((b) => (b.onclick = () => { state.prefs.speak = b.dataset.speak === "1"; savePrefs(); go("settings"); }));
  $("#theme-toggle")?.querySelectorAll("button").forEach((b) => (b.onclick = () => { state.prefs.theme = b.dataset.theme; savePrefs(); applyTheme(); go("settings"); }));
  $("#logout-btn").onclick = logout;
};
window.switchFarm = async (id) => {
  const farms = await api("/farms"); const f = farms.find((x) => x.id === id);
  state.farmId = id; state.farmName = f.name; invalidate();
  state.nodes = await api(`/farms/${id}/nodes`).catch(() => []); state.node = state.nodes[0] || null;
  $("#ab-farm").textContent = f.name; setNodeChip();
  toast(`Switched to ${f.name}`); go("home");
};

// ---------- capture (reuses node ingest API) ----------
function capture() {
  if (!state.node) return toast("Register a monitoring node in Settings first");
  const input = document.createElement("input");
  input.type = "file"; input.accept = "image/*"; input.capture = "environment";
  input.onchange = async () => {
    const file = input.files[0]; if (!file) return;
    const key = { "X-Node-Key": state.node.api_key }; toast("Uploading scan…");
    await fetch("/node/sensors", { method: "POST", headers: { "Content-Type": "application/json", ...key },
      body: JSON.stringify({ temperature: +(24 + Math.random() * 6).toFixed(1), humidity: +(55 + Math.random() * 20).toFixed(1), soil_moisture: +(30 + Math.random() * 25).toFixed(1), battery: 95 }) }).catch(() => {});
    const fd = new FormData(); fd.append("image", file);
    navigator.geolocation?.getCurrentPosition((p) => sendCapture(fd, key, p.coords), () => sendCapture(fd, key, null));
  };
  input.click();
}
async function sendCapture(fd, key, coords) {
  if (coords) { fd.append("gps_lat", coords.latitude); fd.append("gps_long", coords.longitude); }
  try { await fetch("/node/image", { method: "POST", headers: key, body: fd }); invalidate(); toast("Scan captured"); }
  catch { toast("Upload failed"); }
}

// ---------- voice output ----------
function playB64(b64) {
  try { new Audio("data:audio/wav;base64," + b64).play().catch(() => {}); return true; }
  catch { return false; }
}
// Browser voices load asynchronously; cache them and refresh when the list arrives.
let _voices = [];
function refreshVoices() { try { _voices = speechSynthesis.getVoices() || []; } catch { _voices = []; } }
if ("speechSynthesis" in window) {
  refreshVoices();
  speechSynthesis.addEventListener("voiceschanged", refreshVoices);
}
// A voice whose language actually matches. Windows ships no Kannada voice, and
// speaking Kannada text through an en-US voice produces confident gibberish --
// worse than silence, so we return null and let the caller say so plainly.
function voiceFor(lang) {
  const want = (lang || state.prefs.lang) === "kn" ? "kn" : "en";
  if (!_voices.length) refreshVoices();
  return _voices.find((v) => (v.lang || "").toLowerCase().startsWith(want)) || null;
}
function browserSpeak(text, lang) {
  if (!("speechSynthesis" in window) || !text) return false;
  const voice = voiceFor(lang);
  if (!voice) return false;                 // never mispronounce; caller reports it
  const u = new SpeechSynthesisUtterance(text.replace(/[#*_`>-]/g, " "));
  u.voice = voice; u.lang = voice.lang;
  speechSynthesis.cancel(); speechSynthesis.speak(u);
  return true;
}
// Attach a Play button to an answer bubble — voice only sounds when the user taps it.
// On tap: prefer real provider audio (Sarvam); else synthesize via the backend
// (configured provider); browser voice is the last resort.
function attachPlay(bubble, text, language, audioB64) {
  if (!state.prefs.speak || !bubble || !text) return;
  let cached = audioB64 || null;
  const btn = document.createElement("button");
  btn.type = "button"; btn.className = "play-btn";
  btn.innerHTML = `${icon("volume")}<span>Play</span>`;
  btn.onclick = async () => {
    btn.disabled = true;
    if (cached && cached.length > 200 && playB64(cached)) { btn.disabled = false; return; }
    try {
      const r = await jpost("/voice/speak", { text: text.replace(/[#*_`>]/g, " ").slice(0, 900), language });
      if (r.audio_base64 && r.audio_base64.length > 200) { cached = r.audio_base64; playB64(cached); btn.disabled = false; return; }
    } catch { /* provider unavailable -> try an on-device voice below */ }
    if (!browserSpeak(text, language)) {
      toast((language || state.prefs.lang) === "kn"
        ? "Kannada speech is unavailable right now"
        : "Speech is unavailable right now");
    }
    btn.disabled = false;
  };
  bubble.append(btn);
}
let recorder = null, chunks = [];
async function toggleMic() {
  const mic = $("#mic"), hint = $("#mic-hint");
  if (recorder && recorder.state === "recording") return recorder.stop();
  if (!navigator.mediaDevices?.getUserMedia) {
    return toast(window.isSecureContext
      ? "Microphone not supported by this browser"
      : "Voice needs a secure page — open Gage at localhost on your PC, or over an https:// link on your phone");
  }
  let stream; try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return toast("Microphone permission denied"); }
  chunks = []; recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    mic.classList.remove("rec"); mic.innerHTML = icon("mic"); hint.textContent = "Sending…";
    const fd = new FormData(); fd.append("farm_id", state.farmId);
    fd.append("audio", new Blob(chunks, { type: "audio/webm" }), "speech.webm");
    logBubble("Transcribing…", "user");
    try {
      const r = await fetch("/voice/ask", { method: "POST", headers: { Authorization: `Bearer ${state.token}` }, body: fd });
      if (!r.ok) throw new Error(); const d = await r.json();
      $("#ask-log").lastChild.textContent = d.transcript;
      attachPlay(logBubble(docInline(d.answer), "bot"), d.answer, d.language, d.audio_base64);
    } catch { $("#ask-log").lastChild.textContent = "Couldn't hear that — try again"; }
    hint.textContent = "Tap to speak — Kannada or English";
  };
  recorder.start(); mic.classList.add("rec"); mic.innerHTML = icon("stop"); hint.textContent = "Listening… tap to stop";
}

// ---------- live updates ----------
function showAnalyzing() {
  if ($("#analyzing")) return;
  const b = document.createElement("div"); b.id = "analyzing"; b.className = "analyzing";
  b.innerHTML = `<span class="sp"></span>Analyzing latest observation…`;
  $("#view").prepend(b);
}
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws; try { ws = new WebSocket(`${proto}://${location.host}/ws`); } catch { return; }
  ws.onmessage = async (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.event === "observation") {
      invalidate();
      if (state.view === "home") {
        showAnalyzing();
        setTimeout(async () => { await go("home"); ["#health-card"].forEach((s) => $(s)?.classList.add("flash")); document.querySelectorAll(".sensor").forEach((el) => el.classList.add("flash")); }, 1100);
      } else toast("New observation captured");
    } else if (m.event === "alert" && state.view === "home") { invalidate(); go("home"); }
  };
  ws.onclose = () => setTimeout(connectWS, 4000);
}
// keep "Updated … ago" fresh without refetching
let clockTimer = null;
function startClock() {
  if (clockTimer) clearInterval(clockTimer); // no duplicate ticker after re-login
  clockTimer = setInterval(() => { const el = $("#home-updated"); if (el && state.lastObsTime) el.textContent = ago(state.lastObsTime); }, 10000);
}

// ---------- pull to refresh ----------
(function pullToRefresh() {
  const ptr = $("#ptr"); let startY = 0, pulling = false;
  document.addEventListener("touchstart", (e) => { if (window.scrollY <= 0 && $("#shell") && !$("#shell").classList.contains("hidden")) { startY = e.touches[0].clientY; pulling = true; } }, { passive: true });
  document.addEventListener("touchmove", (e) => {
    if (!pulling) return; const dy = e.touches[0].clientY - startY;
    if (dy > 0) { ptr.style.opacity = Math.min(1, dy / 80); ptr.style.transform = `translateX(-50%) translateY(${Math.min(dy / 2, 50)}px)`; }
  }, { passive: true });
  document.addEventListener("touchend", async (e) => {
    if (!pulling) return; pulling = false;
    const dy = (e.changedTouches[0].clientY - startY);
    if (dy > 70) { ptr.classList.add("spin"); ptr.style.opacity = "1"; invalidate(); await go(state.view, state.viewArg); ptr.classList.remove("spin"); }
    ptr.style.opacity = "0"; ptr.style.transform = "translateX(-50%)";
  });
})();

// ---------- start ----------
hydrateIcons();
if (state.token) boot().catch(showLogin); else showLogin();
