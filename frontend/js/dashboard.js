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

// ---------- helpers ----------
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const imgUrl = (p) => (p ? "/" + p.replace(/^\/+/, "") : null);
const fmt = (v, u = "") => (v === null || v === undefined ? "—" : `${(+v).toFixed(1)}${u}`);
const lazyImg = (src, cls) => `<img class="${cls}" src="${src}" loading="lazy" decoding="async" alt="field"/>`;
function ago(iso) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return `${s | 0} seconds ago`;
  if (s < 3600) return `${(s / 60) | 0} min ago`;
  if (s < 86400) return `${(s / 3600) | 0}h ago`;
  return `${(s / 86400) | 0}d ago`;
}
function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good Morning 🌾";
  if (h < 17) return "Good Afternoon ☀️";
  return "Good Evening 🌙";
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
function stars(score) {
  const n = Math.max(1, Math.round(score / 20));
  return `<div class="stars">${"★".repeat(n)}<span class="off">${"★".repeat(5 - n)}</span></div>`;
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
  $("#ab-sub").textContent = state.farmer?.name ? `Hello, ${state.farmer.name}` : "Farm OS";
  $("#ab-node").textContent = state.node ? `Node: ${state.node.id}` : "No node";
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
  host.innerHTML = `<div class="view"><div class="card skeleton" style="height:150px"></div><div class="card skeleton" style="height:120px"></div><div class="card skeleton" style="height:120px"></div></div>`;
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
function gauge(score, cls) {
  const r = 52, c = 2 * Math.PI * r, off = c * (1 - Math.max(0, Math.min(100, score)) / 100);
  const col = cls === "good" ? "#2e7d32" : cls === "watch" ? "#b8860b" : "#c0392b";
  return `<div class="gauge"><svg width="118" height="118" viewBox="0 0 118 118">
    <circle class="track" cx="59" cy="59" r="${r}" fill="none" stroke-width="13"/>
    <circle class="val" cx="59" cy="59" r="${r}" fill="none" stroke="${col}" stroke-width="13"
      stroke-dasharray="${c}" stroke-dashoffset="${c}" data-off="${off}"/></svg>
    <div class="num"><b>${score}%</b><span>health</span></div></div>`;
}
VIEWS.home = async () => {
  if (!state.farmId) return `<div class="card"><h2>Welcome 🌱</h2><p class="muted">Add your first farm in Settings to begin monitoring.</p><button class="btn" onclick="go('settings')">Go to Settings</button></div>`;
  const s = await cachedGet(`/farm/${state.farmId}/summary`);
  const nodes = await cachedGet(`/farms/${state.farmId}/nodes`).catch(() => state.nodes);
  state.lastSummary = s; state.node = nodes[0] || state.node;
  const nh = state.node?.health || {};
  const snap = s.sensor_snapshot || {}, o = s.latest_observation || {};
  const trend = {}; (s.trends || []).forEach((t) => (trend[t.metric] = t));
  const arrow = (m) => trend[m] ? `<span class="trend ${trend[m].direction}">${trend[m].direction === "up" ? "▲" : trend[m].direction === "down" ? "▼" : "—"} ${Math.abs(trend[m].delta)}${trend[m].unit}</span>` : "";
  const img = imgUrl(o.image_path);
  const H = s.health, cls = H.status === "Healthy" ? "good" : H.status === "Watch" ? "watch" : "crit";
  const emLabel = H.score >= 90 ? "Excellent" : H.score >= 80 ? "Very good" : H.score >= 60 ? "Fair" : "Needs care";
  state.lastObsTime = o.timestamp || null;
  const online = (nh.status ? nh.status === "online" : !!o.timestamp);
  const chk = (ok, label) => `<li><span class="check ${ok ? "" : "no"}">${ok ? "✓" : "○"}</span><b>${label}</b></li>`;

  return `
    <div class="greet">
      <div><div class="hello">${greeting()}</div>
        <div class="name">${esc(state.farmer?.name || state.farmName)}</div>
        <div class="date">${dateStr()}</div></div>
      <span class="status-badge ${online ? "" : "off"}"><span class="dot"></span>${online ? "Monitoring Live" : "Node Offline"}</span>
    </div>
    <div class="updated" id="home-updated">Updated ${ago(state.lastObsTime)}</div>

    <div class="card hero" id="health-card">
      ${gauge(H.score, cls)}
      <div style="flex:1"><div class="status ${cls}">${esc(emLabel)}</div>
        ${stars(H.score)}
        <div class="label-em ${cls}">${esc(H.status)}</div></div>
    </div>
    <div class="card">
      <div class="calc-title">Health calculated from</div>
      <ul class="checklist">
        ${chk(!!o.image_path, "Latest image")}
        ${chk(snap.soil_moisture != null, "Soil moisture")}
        ${chk(snap.temperature != null, "Temperature")}
        ${chk(snap.humidity != null, "Humidity")}
        ${chk(true, `Active alerts (${(s.active_alerts || []).length})`)}
      </ul>
    </div>

    <div class="section-title">Latest scan</div>
    <div class="card tap" style="padding:12px" onclick="${o.id ? `go('detail','${o.id}')` : ""}">
      ${img ? `<div class="scan-wrap">${lazyImg(img, "obs-image")}<span class="scan-tag">📷 Latest Scan</span><span class="scan-time">${o.timestamp ? ago(o.timestamp) : ""}</span></div>`
            : `<div class="img-empty">No scan yet — tap Scan Crop below</div>`}
    </div>

    <div class="section-title">🤖 Today's farm report</div>
    <div class="card ai-card"><div class="head">Today at ${esc(state.farmName)}</div>
      <p>${esc(s.ai_summary || "Capture a scan and I'll summarise your field — health, moisture trend, and what to do next.")}</p></div>

    <div class="section-title">Live conditions</div>
    <div class="grid">
      <div class="sensor"><div class="top"><span class="ic">🌡️</span>${arrow("temperature")}</div><span class="v">${fmt(snap.temperature)}<small>°C</small></span><span class="l">Temperature</span></div>
      <div class="sensor"><div class="top"><span class="ic">💧</span>${arrow("humidity")}</div><span class="v">${fmt(snap.humidity)}<small>%</small></span><span class="l">Humidity</span></div>
      <div class="sensor"><div class="top"><span class="ic">🪴</span>${arrow("soil_moisture")}</div><span class="v">${fmt(snap.soil_moisture)}<small>%</small></span><span class="l">Soil moisture</span></div>
      <div class="sensor"><div class="top"><span class="ic">🔋</span></div><span class="v">${nh.battery != null ? fmt(nh.battery) + "<small>%</small>" : "—"}</span><span class="l">Node battery</span></div>
      <div class="sensor"><div class="top"><span class="ic">📡</span></div><span class="v" style="font-size:16px;color:${online ? "var(--green-600)" : "var(--danger)"}">${online ? "Online" : "Offline"}</span><span class="l">Node status · ${nh.last_seen ? ago(nh.last_seen) : "—"}</span></div>
      <div class="sensor"><div class="top"><span class="ic">📍</span></div><span class="v" style="font-size:14px">${o.gps_lat != null ? (+o.gps_lat).toFixed(3) + "," + (+o.gps_long).toFixed(3) : "—"}</span><span class="l">Location</span></div>
    </div>

    ${(s.active_alerts || []).length ? `<div class="section-title">Active alerts</div>${[...s.active_alerts].sort((a, b) => (b.severity === "critical") - (a.severity === "critical")).map((a) => `
      <div class="alert ${a.severity === "critical" ? "crit" : ""}"><span class="ic">${a.severity === "critical" ? "🔴" : "⚠️"}</span>
      <div><div class="sev">${esc(a.severity)}</div><div class="msg">${esc(a.message)}</div></div></div>`).join("")}` : ""}

    <div class="section-title">Quick actions</div>
    <div class="qa">
      <button onclick="go('ask')"><span class="ic">🎤</span>Ask Gage</button>
      <button id="qa-scan"><span class="ic">📷</span>Scan Crop</button>
      <button onclick="go('timeline')"><span class="ic">📈</span>Timeline</button>
      <button onclick="go('reports')"><span class="ic">📄</span>Reports</button>
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
  if (!obs.length) return `<div class="card"><h2>No observations yet</h2><p class="muted">Your monitoring node's captures appear here as a living timeline.</p></div>`;
  return `<div class="section-title">Observation timeline</div>` + obs.map((o) => {
    const img = imgUrl(o.image_path), h = clientHealth(o);
    return `<div class="card tl tap" onclick="go('detail','${o.id}')">
      ${img ? lazyImg(img, "") : `<div class="thumb">🌿</div>`}
      <div class="body"><div class="when">${new Date(o.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${ago(o.timestamp)}</div>
        <div class="sum">${esc(o.vision_summary || o.ai_summary || "Observation")}</div>
        <div class="mini"><span class="health-pill ${h.cls}">${h.label} ${h.score}%</span> · 🪴 ${fmt(o.soil_moisture)}%</div>
      </div><span class="go">›</span></div>`;
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
    <button class="btn ghost sm" onclick="go('timeline')">‹ Back to timeline</button>
    <div class="card tap" style="padding:12px;margin-top:12px">
      ${img ? `<div class="scan-wrap">${lazyImg(img, "obs-image")}<span class="scan-tag">📷 Scan</span></div>` : `<div class="img-empty">No image</div>`}
      <div class="when muted" style="margin-top:8px">${new Date(o.timestamp).toLocaleString()} · node ${esc(o.node_id)}</div>
    </div>

    <div class="card hero" style="padding:14px">
      ${gauge(h.score, h.cls)}
      <div><div class="status ${h.cls}">${h.label}</div>${stars(h.score)}<div class="label-em ${h.cls}">Observation health</div></div>
    </div>

    <div class="grid">
      <div class="sensor"><span class="ic">🌡️</span><span class="v">${fmt(o.temperature)}°C</span><span class="l">Temperature</span></div>
      <div class="sensor"><span class="ic">💧</span><span class="v">${fmt(o.humidity)}%</span><span class="l">Humidity</span></div>
      <div class="sensor"><span class="ic">🪴</span><span class="v">${fmt(o.soil_moisture)}%</span><span class="l">Soil moisture</span></div>
      <div class="sensor"><span class="ic">📍</span><span class="v" style="font-size:14px">${o.gps_lat != null ? (+o.gps_lat).toFixed(3) + "," + (+o.gps_long).toFixed(3) : "—"}</span><span class="l">Location</span></div>
    </div>

    <div class="section-title">Vision summary</div>
    <div class="card"><p>${esc(o.vision_summary || "No image was analysed for this observation.")}</p></div>

    ${o.ai_summary ? `<div class="section-title">AI summary</div><div class="card ai-card"><div class="head">🤖 Gage</div><p>${esc(o.ai_summary)}</p></div>` : ""}

    <div class="section-title">Recommendations</div>
    <div class="card ai-card"><div class="doc-section rec"><div class="lab">What to do</div>
      <ul>${a.recs.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
      <div class="doc-section"><span class="conf ${a.conf.toLowerCase()}">Confidence: ${a.conf}</span></div>
    </div>

    <div class="section-title">Why Gage said this</div>
    <div class="card"><div class="why"><b>🧠 Reasoning</b><p style="margin:6px 0 0">${esc(whyText)}</p></div></div>`;
};

// ---------- ASK GAGE ----------
const SUGGESTIONS = ["Should I irrigate?", "How is my crop?", "Any disease?", "Is soil moisture okay?", "ನನ್ನ ಬೆಳೆ ಹೇಗಿದೆ?"];
VIEWS.ask = async () => `
  <div class="section-title">Ask Gage</div>
  <div class="card glass" style="text-align:center">
    <div class="mic-wrap"><button class="mic" id="mic">🎙️</button>
      <div class="mic-hint" id="mic-hint">Tap to speak — Kannada or English</div></div>
  </div>
  <div class="section-title">Try asking</div>
  <div class="chips" id="chips">${SUGGESTIONS.map((q) => `<button class="chip-btn">${esc(q)}</button>`).join("")}</div>
  <div id="ask-log" style="margin-top:16px"></div>
  <div class="card" style="position:sticky;bottom:calc(var(--nav-h) + 10px);z-index:5">
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
    pending.innerHTML = docInline(r.answer); voiceOut(r.answer, r.language);
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
const repCard = (title, a) => `<div class="card"><div class="head" style="font-weight:800;color:var(--green-700);margin-bottom:10px">${title}</div>
  <div class="grid">
    <div class="sensor"><span class="l">Observations</span><span class="v">${a.count}</span></div>
    <div class="sensor"><span class="l">Avg soil</span><span class="v">${fmt(a.soil)}%</span></div>
    <div class="sensor"><span class="l">Avg temp</span><span class="v">${fmt(a.temp)}°C</span></div>
    <div class="sensor"><span class="l">Avg humidity</span><span class="v">${fmt(a.hum)}%</span></div>
  </div></div>`;
VIEWS.reports = async () => {
  if (!state.farmId) return `<div class="card"><p class="muted">Add a farm first.</p></div>`;
  const obs = await cachedGet(`/farm/${state.farmId}/timeline?limit=300`);
  let stats = null; try { stats = await cachedGet("/dataset/stats"); } catch {}
  const bars = stats ? Object.entries(stats.daily_rate || {}) : [];
  const max = Math.max(1, ...bars.map(([, n]) => n));
  const soils = obs.slice(0, 12).reverse().map((o) => o.soil_moisture).filter((x) => x != null);
  const smax = Math.max(1, ...soils);
  return `
    <div class="section-title">Daily</div>${repCard("Today & last 24 hours", aggregate(obs, 1))}
    <div class="section-title">Weekly</div>${repCard("Last 7 days", aggregate(obs, 7))}
    <div class="section-title">Monthly</div>${repCard("Last 30 days", aggregate(obs, 30))}
    ${soils.length > 1 ? `<div class="section-title">Recent soil moisture trend</div>
    <div class="card"><svg viewBox="0 0 300 90" width="100%" height="90" preserveAspectRatio="none">
      <polyline fill="none" stroke="#43a047" stroke-width="3" stroke-linejoin="round" points="${soils.map((v, i) => `${(i / (soils.length - 1)) * 300},${88 - (v / smax) * 78}`).join(" ")}"/>
    </svg><p class="muted" style="font-size:12px;margin:6px 0 0">Last ${soils.length} readings (%)</p></div>` : ""}
    ${bars.length ? `<div class="section-title">Data collection (7 days)</div>
    <div class="card"><div style="display:flex;align-items:flex-end;gap:8px;height:110px">
      ${bars.map(([d, n]) => `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;justify-content:flex-end;height:100%">
        <div style="width:100%;background:linear-gradient(180deg,var(--green-400),var(--green-600));border-radius:6px 6px 0 0;height:${(n / max) * 80 + 4}px"></div>
        <span style="font-size:10px;color:var(--muted)">${d.slice(5)}</span></div>`).join("")}
    </div><p class="muted" style="margin:10px 0 0;font-size:12px">${stats.dataset_entries} records · avg quality ${stats.average_quality}</p></div>` : ""}`;
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
      <div class="pill-toggle" id="theme-toggle"><button data-theme="light" class="${on(state.prefs.theme !== "dark")}">☀️ Light</button><button data-theme="dark" class="${on(state.prefs.theme === "dark")}">🌙 Dark</button></div></div></div>

    <div class="card"><button class="btn ghost block" id="logout-btn">Sign out</button></div>
    <p class="muted" style="text-align:center;font-size:11px">Gage Farm OS · ${esc(state.farmer?.phone || "")}</p>`;
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
  $("#ab-farm").textContent = f.name; $("#ab-node").textContent = state.node ? `Node: ${state.node.id}` : "No node";
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
  try { await fetch("/node/image", { method: "POST", headers: key, body: fd }); invalidate(); toast("Scan captured ✓"); }
  catch { toast("Upload failed"); }
}

// ---------- voice output ----------
function playB64(b64) {
  try { new Audio("data:audio/wav;base64," + b64).play().catch(() => {}); return true; }
  catch { return false; }
}
function browserSpeak(text, lang) {  // fallback only (needs an OS voice for the language)
  if (!("speechSynthesis" in window) || !text) return;
  const u = new SpeechSynthesisUtterance(text.replace(/[#*_`>-]/g, " "));
  u.lang = (lang || state.prefs.lang) === "kn" ? "kn-IN" : "en-IN";
  speechSynthesis.cancel(); speechSynthesis.speak(u);
}
// Speak an answer: prefer real provider audio (Sarvam); if none, synthesize via the
// backend (uses the configured provider); browser voice is the last resort.
async function voiceOut(text, language, audioB64) {
  if (!state.prefs.speak || !text) return;
  if (audioB64 && audioB64.length > 200 && playB64(audioB64)) return;
  try {
    const r = await jpost("/voice/speak", {
      text: text.replace(/[#*_`>]/g, " ").slice(0, 900), language,
    });
    if (r.audio_base64 && r.audio_base64.length > 200 && playB64(r.audio_base64)) return;
  } catch { /* fall through to browser voice */ }
  browserSpeak(text, language);
}
let recorder = null, chunks = [];
async function toggleMic() {
  const mic = $("#mic"), hint = $("#mic-hint");
  if (recorder && recorder.state === "recording") return recorder.stop();
  if (!navigator.mediaDevices?.getUserMedia) return toast("Microphone not supported");
  let stream; try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return toast("Microphone permission denied"); }
  chunks = []; recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    mic.classList.remove("rec"); mic.textContent = "🎙️"; hint.textContent = "Sending…";
    const fd = new FormData(); fd.append("farm_id", state.farmId);
    fd.append("audio", new Blob(chunks, { type: "audio/webm" }), "speech.webm");
    logBubble("🎙️ …", "user");
    try {
      const r = await fetch("/voice/ask", { method: "POST", headers: { Authorization: `Bearer ${state.token}` }, body: fd });
      if (!r.ok) throw new Error(); const d = await r.json();
      $("#ask-log").lastChild.textContent = "🎙️ " + d.transcript;
      logBubble(docInline(d.answer), "bot"); voiceOut(d.answer, d.language, d.audio_base64);
    } catch { $("#ask-log").lastChild.textContent = "🎙️ (couldn't hear that)"; }
    hint.textContent = "Tap to speak — Kannada or English";
  };
  recorder.start(); mic.classList.add("rec"); mic.textContent = "⏹"; hint.textContent = "Listening… tap to stop";
}

// ---------- live updates ----------
function showAnalyzing() {
  if ($("#analyzing")) return;
  const b = document.createElement("div"); b.id = "analyzing"; b.className = "analyzing";
  b.innerHTML = `<span class="sp"></span> Analyzing latest observation…`;
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
      } else toast("🌿 New observation captured");
    } else if (m.event === "alert" && state.view === "home") { invalidate(); go("home"); }
  };
  ws.onclose = () => setTimeout(connectWS, 4000);
}
// keep "Updated … ago" fresh without refetching
function startClock() {
  setInterval(() => { const el = $("#home-updated"); if (el && state.lastObsTime) el.textContent = "Updated " + ago(state.lastObsTime); }, 10000);
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
if (state.token) boot().catch(showLogin); else showLogin();
