"use strict";
/* Gage — Farm Operating System (single-page app over the existing backend API). */

// ---------- state + helpers ----------
const state = {
  token: localStorage.getItem("gage_token") || null,
  farmer: null,
  farmId: null,
  farmName: "Farm",
  nodes: [],
  node: null,
  obsCache: {},           // id -> observation (for the detail page)
  prefs: JSON.parse(localStorage.getItem("gage_prefs") || '{"lang":"en","speak":true}'),
  view: "home",
};
const savePrefs = () => localStorage.setItem("gage_prefs", JSON.stringify(state.prefs));

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const imgUrl = (p) => (p ? "/" + p.replace(/^\/+/, "") : null);
const fmt = (v, u = "") => (v === null || v === undefined ? "—" : `${(+v).toFixed(1)}${u}`);
function ago(iso) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s | 0}s ago`;
  if (s < 3600) return `${(s / 60) | 0}m ago`;
  if (s < 86400) return `${(s / 3600) | 0}h ago`;
  return `${(s / 86400) | 0}d ago`;
}
function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg; document.body.append(t);
  setTimeout(() => t.remove(), 2600);
}
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers);
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (r.status === 401) { logout(); throw new Error("unauthorized"); }
  if (!r.ok) throw new Error(await r.text().catch(() => r.status));
  return r.status === 204 ? null : r.json();
}
const jpost = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

// ---------- crop-doctor answer parser ----------
function parseDoc(text) {
  const grab = (name, stops) => {
    const re = new RegExp(`${name}\\s*:?\\s*([\\s\\S]*?)(?=(?:${stops.join("|")})\\s*:|$)`, "i");
    const m = text.match(re); return m ? m[1].trim() : "";
  };
  const observation = grab("Observation", ["Analysis", "Confidence", "Recommendations"]);
  const analysis = grab("Analysis", ["Confidence", "Recommendations"]);
  const confidence = grab("Confidence", ["Recommendations"]);
  const recommendations = grab("Recommendations", ["$"]);
  const anyStruct = observation || analysis || confidence || recommendations;
  return { observation, analysis, confidence, recommendations, raw: text, structured: !!anyStruct };
}
const confClass = (c) => /high/i.test(c) ? "high" : /low/i.test(c) ? "low" : "medium";
const confWord = (c) => (c.match(/high|medium|low/i) || ["Medium"])[0];
function bullets(text) {
  const items = text.split("\n").map((l) => l.replace(/^[-•]\s*/, "").trim()).filter(Boolean);
  if (items.length <= 1) return `<p>${esc(text || "—")}</p>`;
  return `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
}
function docCard(answer) {
  const d = parseDoc(answer);
  if (!d.structured) return `<div class="card ai-card"><p>${esc(answer)}</p></div>`;
  return `<div class="card ai-card">
    ${d.observation ? `<div class="doc-section obs"><div class="lab">Observation · what I can see</div>${bullets(d.observation)}</div>` : ""}
    ${d.analysis ? `<div class="doc-section ana"><div class="lab">Analysis · what it likely means</div><p>${esc(d.analysis)}</p></div>` : ""}
    ${d.confidence ? `<div class="doc-section"><span class="conf ${confClass(d.confidence)}">Confidence: ${esc(confWord(d.confidence))}</span></div>` : ""}
    ${d.recommendations ? `<div class="doc-section rec"><div class="lab">Recommendations</div>${bullets(d.recommendations)}</div>` : ""}
  </div>`;
}

// ---------- auth ----------
function showLogin() {
  $("#login").classList.remove("hidden");
  $("#shell").classList.add("hidden");
}
function logout() {
  state.token = null; localStorage.removeItem("gage_token"); showLogin();
}
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
    const path = registerMode ? "/auth/register" : "/auth/login";
    const r = await jpost(path, { phone, password });
    state.token = r.access_token; localStorage.setItem("gage_token", state.token);
    await boot();
  } catch {
    $("#lg-msg").textContent = registerMode ? "Could not register (phone may exist)." : "Invalid phone or password.";
  }
};

// ---------- boot ----------
async function boot() {
  try {
    state.farmer = await api("/auth/me");
    const farms = await api("/farms");
    if (!farms.length) {         // brand-new farmer with no farm yet
      state.farmId = null;
    } else {
      state.farmId = farms[0].id; state.farmName = farms[0].name;
    }
  } catch { return; }
  if (state.farmId) {
    try { state.nodes = await api(`/farms/${state.farmId}/nodes`); } catch { state.nodes = []; }
    state.node = state.nodes[0] || null;
  }
  $("#login").classList.add("hidden");
  $("#shell").classList.remove("hidden");
  $("#ab-farm").textContent = state.farmName;
  $("#ab-sub").textContent = state.farmer?.name ? `Hello, ${state.farmer.name}` : "Farm OS";
  $("#ab-node").textContent = state.node ? `Node: ${state.node.id}` : "No node";
  go(state.view || "home");
  connectWS();
}

// ---------- router ----------
document.querySelectorAll(".nav button").forEach((b) => {
  b.onclick = () => go(b.dataset.nav);
});
function setNav(name) {
  document.querySelectorAll(".nav button").forEach((b) => b.classList.toggle("on", b.dataset.nav === name));
}
const VIEWS = {};
async function go(name, arg) {
  state.view = name; setNav(name);
  const host = $("#view");
  host.innerHTML = `<div class="view"><div class="card skeleton" style="height:120px"></div><div class="card skeleton" style="height:160px"></div></div>`;
  try {
    host.innerHTML = `<div class="view">${await VIEWS[name](arg)}</div>`;
    if (WIRE[name]) WIRE[name](arg);
  } catch (e) {
    host.innerHTML = `<div class="view"><div class="card"><p class="muted">Could not load this page. ${esc(e.message || "")}</p></div></div>`;
  }
  host.scrollTop = 0; window.scrollTo(0, 0);
}
const WIRE = {};

// ---------- HOME ----------
function gauge(score, status) {
  const r = 46, c = 2 * Math.PI * r, off = c * (1 - Math.max(0, Math.min(100, score)) / 100);
  const cls = status === "Healthy" ? "good" : status === "Watch" ? "watch" : "crit";
  const col = cls === "good" ? "#2e7d32" : cls === "watch" ? "#b8860b" : "#c0392b";
  return `<div class="gauge"><svg width="104" height="104" viewBox="0 0 104 104">
    <circle class="track" cx="52" cy="52" r="${r}" fill="none" stroke-width="12"/>
    <circle class="val" cx="52" cy="52" r="${r}" fill="none" stroke="${col}" stroke-width="12"
      stroke-dasharray="${c}" stroke-dashoffset="${off}"/></svg>
    <div class="num"><b>${score}</b><span>/100</span></div></div>`;
}
VIEWS.home = async () => {
  if (!state.farmId) return `<div class="card"><h2>Welcome 🌱</h2><p class="muted">Add your first farm in Settings to begin.</p><button class="btn" onclick="go('settings')">Go to Settings</button></div>`;
  const s = await api(`/farm/${state.farmId}/summary`);
  const snap = s.sensor_snapshot || {};
  const trend = {}; (s.trends || []).forEach((t) => (trend[t.metric] = t));
  const trChip = (m) => trend[m] ? `<span class="t ${trend[m].direction === "up" ? "up" : "down"}">${trend[m].direction === "up" ? "▲" : trend[m].direction === "down" ? "▼" : "■"} ${Math.abs(trend[m].delta)}${trend[m].unit}</span>` : "";
  const img = imgUrl(s.latest_observation?.image_path);
  const cls = s.health.status === "Healthy" ? "good" : s.health.status === "Watch" ? "watch" : "crit";
  return `
    <div class="card hero tap">
      ${gauge(s.health.score, s.health.status)}
      <div><div class="status ${cls}">${esc(s.health.status)}</div>
      <ul class="reasons">${(s.health.reasons || []).slice(0, 3).map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
    </div>

    <div class="section-title">Latest observation</div>
    <div class="card" style="padding:12px">
      ${img ? `<img class="obs-image" src="${img}" alt="field"/>` : `<div class="img-empty">No image yet — capture one below</div>`}
    </div>

    <div class="grid">
      <div class="sensor"><span class="ic">🌡️</span><span class="v">${fmt(snap.temperature)}<small style="font-size:13px">°C</small></span><span class="l">Temperature ${trChip("temperature")}</span></div>
      <div class="sensor"><span class="ic">💧</span><span class="v">${fmt(snap.humidity)}<small style="font-size:13px">%</small></span><span class="l">Humidity ${trChip("humidity")}</span></div>
      <div class="sensor"><span class="ic">🪴</span><span class="v">${fmt(snap.soil_moisture)}<small style="font-size:13px">%</small></span><span class="l">Soil moisture ${trChip("soil_moisture")}</span></div>
      <div class="sensor"><span class="ic">📍</span><span class="v" style="font-size:15px">${s.latest_observation?.gps_lat != null ? (+s.latest_observation.gps_lat).toFixed(3) + ", " + (+s.latest_observation.gps_long).toFixed(3) : "—"}</span><span class="l">Location</span></div>
    </div>

    ${(s.active_alerts || []).length ? `<div class="section-title">Active alerts</div>${s.active_alerts.map((a) => `
      <div class="alert ${a.severity === "critical" ? "crit" : ""}"><span class="ic">${a.severity === "critical" ? "🔴" : "⚠️"}</span>
      <div><div class="sev">${esc(a.severity)}</div><div class="msg">${esc(a.message)}</div></div></div>`).join("")}` : ""}

    <div class="section-title">Gage's summary</div>
    <div class="card ai-card"><div class="head">🧑‍🌾 Today at ${esc(state.farmName)}</div>
      <p>${esc(s.ai_summary || "Capture an observation and I'll summarise your field's condition.")}</p></div>

    <div class="section-title">Quick actions</div>
    <div class="qa">
      <button onclick="go('ask')"><span class="ic">🎙️</span>Ask Gage</button>
      <button id="qa-capture"><span class="ic">📷</span>Capture</button>
      <button onclick="go('timeline')"><span class="ic">🕒</span>Timeline</button>
      <button onclick="go('reports')"><span class="ic">📊</span>Reports</button>
    </div>`;
};
WIRE.home = () => { const b = $("#qa-capture"); if (b) b.onclick = capture; };

// ---------- TIMELINE ----------
VIEWS.timeline = async () => {
  if (!state.farmId) return `<div class="card"><p class="muted">Add a farm first.</p></div>`;
  const obs = await api(`/farm/${state.farmId}/timeline?limit=50`);
  obs.forEach((o) => (state.obsCache[o.id] = o));
  if (!obs.length) return `<div class="card"><h2>No observations yet</h2><p class="muted">Your monitoring node's captures will appear here as a timeline.</p></div>`;
  return `<div class="section-title">Observation timeline</div>` + obs.map((o) => {
    const img = imgUrl(o.image_path);
    return `<div class="card tl tap" onclick="go('detail','${o.id}')">
      ${img ? `<img src="${img}"/>` : `<div class="thumb">🌿</div>`}
      <div class="body"><div class="when">${new Date(o.timestamp).toLocaleString()} · ${ago(o.timestamp)}</div>
        <div class="sum">${esc(o.vision_summary || o.ai_summary || "Observation")}</div>
        <div class="mini">🌡️ ${fmt(o.temperature)}°C · 💧 ${fmt(o.humidity)}% · 🪴 ${fmt(o.soil_moisture)}%</div>
      </div><span class="go">›</span></div>`;
  }).join("");
};

// ---------- OBSERVATION DETAIL ----------
VIEWS.detail = async (id) => {
  const o = state.obsCache[id];
  if (!o) return `<div class="card"><p class="muted">Observation not found.</p><button class="btn" onclick="go('timeline')">Back</button></div>`;
  const img = imgUrl(o.image_path);
  const isLatest = true; // analysis grounds on current farm state
  return `
    <button class="btn ghost sm" onclick="go('timeline')">‹ Back to timeline</button>
    <div class="card" style="padding:12px;margin-top:12px">
      ${img ? `<img class="obs-image" src="${img}"/>` : `<div class="img-empty">No image</div>`}
      <div class="when muted" style="margin-top:8px">${new Date(o.timestamp).toLocaleString()} · node ${esc(o.node_id)}</div>
    </div>
    <div class="grid">
      <div class="sensor"><span class="ic">🌡️</span><span class="v">${fmt(o.temperature)}°C</span><span class="l">Temperature</span></div>
      <div class="sensor"><span class="ic">💧</span><span class="v">${fmt(o.humidity)}%</span><span class="l">Humidity</span></div>
      <div class="sensor"><span class="ic">🪴</span><span class="v">${fmt(o.soil_moisture)}%</span><span class="l">Soil moisture</span></div>
      <div class="sensor"><span class="ic">📍</span><span class="v" style="font-size:14px">${o.gps_lat != null ? (+o.gps_lat).toFixed(3) + "," + (+o.gps_long).toFixed(3) : "—"}</span><span class="l">Location</span></div>
    </div>
    <div class="section-title">Vision summary</div>
    <div class="card"><p>${esc(o.vision_summary || "No image was analysed for this observation.")}</p></div>
    <div class="section-title">AI analysis</div>
    <div id="detail-analysis"><div class="card"><p class="muted">Gage can analyse this field and explain its reasoning.</p>
      <button class="btn" id="analyze-btn">🧑‍🌾 Get Gage's analysis</button></div></div>`;
};
WIRE.detail = (id) => {
  const btn = $("#analyze-btn");
  if (btn) btn.onclick = async () => {
    btn.textContent = "Analysing…"; btn.disabled = true;
    try {
      const r = await jpost("/chat", { farm_id: state.farmId, question: "Give me a full analysis of my field with observation, analysis, confidence and recommendations." });
      $("#detail-analysis").innerHTML = docCard(r.answer) +
        `<div class="card ai-card"><div class="doc-section obs"><div class="lab">Why Gage said this</div>
         <p class="muted">Grounded in this farm's latest observation, sensor readings, active alerts, recent history and the sugarcane knowledge base.</p></div></div>`;
      if (state.prefs.speak) speak(r.answer, r.language);
    } catch { $("#detail-analysis").innerHTML = `<div class="card"><p class="muted">Analysis unavailable right now.</p></div>`; }
  };
};

// ---------- ASK GAGE ----------
const SUGGESTIONS = [
  "How is my field today?", "Should I irrigate now?", "Any disease risk?",
  "Is soil moisture okay?", "How is my crop growth?", "ಗಿಡ ಹೇಗಿದೆ?",
];
VIEWS.ask = async () => `
  <div class="section-title">Ask Gage</div>
  <div class="card" style="text-align:center">
    <div class="mic-wrap">
      <button class="mic" id="mic">🎙️</button>
      <div class="mic-hint" id="mic-hint">Tap to speak — Kannada or English</div>
    </div>
  </div>
  <div class="section-title">Try asking</div>
  <div class="chips" id="chips">${SUGGESTIONS.map((q) => `<button class="chip-btn">${esc(q)}</button>`).join("")}</div>
  <div id="ask-log" style="margin-top:16px"></div>
  <div class="card" style="position:sticky;bottom:calc(var(--nav-h) + 10px)">
    <div class="row"><input id="ask-input" placeholder="Type your question…" />
      <button class="btn" id="ask-send" style="flex:0 0 auto">Ask</button></div>
  </div>`;
WIRE.ask = () => {
  $("#chips").querySelectorAll(".chip-btn").forEach((c) => (c.onclick = () => askText(c.textContent)));
  $("#ask-send").onclick = () => { const v = $("#ask-input").value.trim(); if (v) { $("#ask-input").value = ""; askText(v); } };
  $("#ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#ask-send").click(); });
  $("#mic").onclick = toggleMic;
};
function logBubble(text, who) {
  const log = $("#ask-log"); if (!log) return null;
  const d = document.createElement("div"); d.className = `bubble ${who}`; d.innerHTML = text;
  log.append(d); d.scrollIntoView({ behavior: "smooth", block: "nearest" }); return d;
}
async function askText(q) {
  logBubble(esc(q), "user");
  const pending = logBubble("<span class='muted'>Gage is thinking…</span>", "bot");
  try {
    const r = await jpost("/chat", { farm_id: state.farmId, question: q });
    pending.outerHTML = `<div class="bubble bot">${docCardInline(r.answer)}</div>`;
    if (state.prefs.speak) speak(r.answer, r.language);
  } catch { pending.textContent = "Sorry, I'm unavailable right now."; }
}
function docCardInline(answer) {
  const d = parseDoc(answer);
  if (!d.structured) return esc(answer);
  return `${d.observation ? `<b>Observation</b>${bullets(d.observation)}` : ""}
    ${d.analysis ? `<b>Analysis</b><p>${esc(d.analysis)}</p>` : ""}
    ${d.confidence ? `<span class="conf ${confClass(d.confidence)}">Confidence: ${esc(confWord(d.confidence))}</span>` : ""}
    ${d.recommendations ? `<b style="display:block;margin-top:8px">Recommendations</b>${bullets(d.recommendations)}` : ""}`;
}

// ---------- REPORTS ----------
function aggregate(obs, days) {
  const cutoff = Date.now() - days * 86400000;
  const inRange = obs.filter((o) => new Date(o.timestamp).getTime() >= cutoff);
  const avg = (k) => { const v = inRange.map((o) => o[k]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  return { count: inRange.length, temp: avg("temperature"), hum: avg("humidity"), soil: avg("soil_moisture") };
}
function reportCard(title, a) {
  return `<div class="card"><div class="head" style="font-weight:700;color:var(--green-700);margin-bottom:8px">${title}</div>
    <div class="grid">
      <div class="sensor"><span class="l">Observations</span><span class="v">${a.count}</span></div>
      <div class="sensor"><span class="l">Avg soil</span><span class="v">${fmt(a.soil)}%</span></div>
      <div class="sensor"><span class="l">Avg temp</span><span class="v">${fmt(a.temp)}°C</span></div>
      <div class="sensor"><span class="l">Avg humidity</span><span class="v">${fmt(a.hum)}%</span></div>
    </div></div>`;
}
VIEWS.reports = async () => {
  if (!state.farmId) return `<div class="card"><p class="muted">Add a farm first.</p></div>`;
  const obs = await api(`/farm/${state.farmId}/timeline?limit=300`);
  let stats = null; try { stats = await api("/dataset/stats"); } catch { stats = null; }
  const bars = stats ? Object.entries(stats.daily_rate || {}) : [];
  const max = Math.max(1, ...bars.map(([, n]) => n));
  return `
    <div class="section-title">Daily report</div>${reportCard("Today & last 24h", aggregate(obs, 1))}
    <div class="section-title">Weekly report</div>${reportCard("Last 7 days", aggregate(obs, 7))}
    <div class="section-title">Monthly report</div>${reportCard("Last 30 days", aggregate(obs, 30))}
    ${bars.length ? `<div class="section-title">Data collection (7 days)</div>
    <div class="card"><div style="display:flex;align-items:flex-end;gap:8px;height:110px">
      ${bars.map(([d, n]) => `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;justify-content:flex-end;height:100%">
        <div style="width:100%;background:var(--green-500);border-radius:6px 6px 0 0;height:${(n / max) * 80 + 4}px"></div>
        <span style="font-size:10px;color:var(--muted)">${d.slice(5)}</span></div>`).join("")}
    </div><p class="muted" style="margin:10px 0 0;font-size:12px">${stats.dataset_entries} records collected · avg quality ${stats.average_quality}</p></div>` : ""}`;
};

// ---------- SETTINGS ----------
VIEWS.settings = async () => {
  const farms = await api("/farms").catch(() => []);
  let nodes = [];
  if (state.farmId) nodes = await api(`/farms/${state.farmId}/nodes`).catch(() => []);
  return `
    <div class="section-title">Farms</div>
    <div class="card">${farms.map((f) => `<div class="list-item"><div><b>${esc(f.name)}</b><div class="kv">${esc(f.crop_type)} · ${esc(f.village || "—")}</div></div>${f.id === state.farmId ? '<span class="conf high">Active</span>' : `<button class="btn ghost sm" onclick="switchFarm(${f.id})">Use</button>`}</div>`).join("") || '<p class="muted">No farms yet.</p>'}
      <div class="row" style="margin-top:12px"><input id="nf-name" placeholder="New farm name"/><button class="btn" id="add-farm" style="flex:0 0 auto">Add</button></div>
    </div>

    <div class="section-title">Monitoring nodes</div>
    <div class="card">${nodes.map((n) => `<div class="list-item"><div><b>${esc(n.id)}</b><div class="kv">${esc(n.name || "node")} · key <span class="code">${esc(n.api_key)}</span></div></div><span class="conf ${n.health && n.health.status === "offline" ? "low" : "high"}">${n.health ? esc(n.health.status) : "new"}</span></div>`).join("") || '<p class="muted">No nodes registered.</p>'}
      ${state.farmId ? `<div class="row" style="margin-top:12px"><input id="nn-id" placeholder="node-id (device)"/><button class="btn" id="add-node" style="flex:0 0 auto">Register</button></div>` : ""}
    </div>

    <div class="section-title">Language</div>
    <div class="card"><div class="list-item"><span>Assistant & voice language</span>
      <div class="pill-toggle" id="lang-toggle">
        <button data-lang="en" class="${state.prefs.lang === "en" ? "on" : ""}">English</button>
        <button data-lang="kn" class="${state.prefs.lang === "kn" ? "on" : ""}">ಕನ್ನಡ</button>
      </div></div></div>

    <div class="section-title">Voice preferences</div>
    <div class="card"><div class="list-item"><span>Speak answers aloud</span>
      <div class="pill-toggle" id="speak-toggle">
        <button data-speak="1" class="${state.prefs.speak ? "on" : ""}">On</button>
        <button data-speak="0" class="${!state.prefs.speak ? "on" : ""}">Off</button>
      </div></div></div>

    <div class="card"><button class="btn ghost block" id="logout-btn">Sign out</button></div>`;
};
WIRE.settings = () => {
  const af = $("#add-farm"); if (af) af.onclick = async () => {
    const name = $("#nf-name").value.trim(); if (!name) return;
    await jpost("/farms", { name }); toast("Farm added"); go("settings");
  };
  const an = $("#add-node"); if (an) an.onclick = async () => {
    const id = $("#nn-id").value.trim(); if (!id) return;
    try { await jpost(`/farms/${state.farmId}/nodes`, { id }); toast("Node registered"); go("settings"); }
    catch { toast("Could not register node"); }
  };
  $("#lang-toggle")?.querySelectorAll("button").forEach((b) => b.onclick = () => {
    state.prefs.lang = b.dataset.lang; savePrefs(); go("settings");
  });
  $("#speak-toggle")?.querySelectorAll("button").forEach((b) => b.onclick = () => {
    state.prefs.speak = b.dataset.speak === "1"; savePrefs(); go("settings");
  });
  $("#logout-btn").onclick = logout;
};
window.switchFarm = async (id) => {
  const farms = await api("/farms"); const f = farms.find((x) => x.id === id);
  state.farmId = id; state.farmName = f.name;
  state.nodes = await api(`/farms/${id}/nodes`).catch(() => []); state.node = state.nodes[0] || null;
  $("#ab-farm").textContent = f.name; $("#ab-node").textContent = state.node ? `Node: ${state.node.id}` : "No node";
  toast(`Switched to ${f.name}`); go("home");
};

// ---------- capture (reuses the node ingest API) ----------
function capture() {
  if (!state.node) return toast("Register a monitoring node first");
  const input = document.createElement("input");
  input.type = "file"; input.accept = "image/*"; input.capture = "environment";
  input.onchange = async () => {
    const file = input.files[0]; if (!file) return;
    const key = { "X-Node-Key": state.node.api_key };
    toast("Uploading capture…");
    // sensors (demo values) then image -> backend merges into one observation
    await fetch("/node/sensors", { method: "POST", headers: { "Content-Type": "application/json", ...key },
      body: JSON.stringify({ temperature: +(24 + Math.random() * 6).toFixed(1), humidity: +(55 + Math.random() * 20).toFixed(1), soil_moisture: +(30 + Math.random() * 25).toFixed(1), battery: 95 }) }).catch(() => {});
    const fd = new FormData(); fd.append("image", file);
    navigator.geolocation?.getCurrentPosition(
      (p) => sendCapture(fd, key, p.coords), () => sendCapture(fd, key, null));
  };
  input.click();
}
async function sendCapture(fd, key, coords) {
  if (coords) { fd.append("gps_lat", coords.latitude); fd.append("gps_long", coords.longitude); }
  try { await fetch("/node/image", { method: "POST", headers: key, body: fd }); toast("Observation captured ✓"); if (state.view === "home") go("home"); }
  catch { toast("Upload failed"); }
}

// ---------- voice ----------
function speak(text, lang) {
  if (!("speechSynthesis" in window) || !text) return;
  const plain = text.replace(/[#*_`>-]/g, " ");
  const u = new SpeechSynthesisUtterance(plain);
  u.lang = (lang || state.prefs.lang) === "kn" ? "kn-IN" : "en-IN";
  speechSynthesis.cancel(); speechSynthesis.speak(u);
}
let recorder = null, chunks = [];
async function toggleMic() {
  const mic = $("#mic"), hint = $("#mic-hint");
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  if (!navigator.mediaDevices?.getUserMedia) return toast("Microphone not supported");
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { return toast("Microphone permission denied"); }
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
      if (!r.ok) throw new Error();
      const d = await r.json();
      $("#ask-log").lastChild.textContent = "🎙️ " + d.transcript;
      logBubble(docCardInline(d.answer), "bot");
      if (state.prefs.speak) speak(d.answer, d.language);
    } catch { $("#ask-log").lastChild.textContent = "🎙️ (couldn't hear that)"; }
    hint.textContent = "Tap to speak — Kannada or English";
  };
  recorder.start(); mic.classList.add("rec"); mic.textContent = "⏹"; hint.textContent = "Listening… tap to stop";
}

// ---------- live updates ----------
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws;
  try { ws = new WebSocket(`${proto}://${location.host}/ws`); } catch { return; }
  ws.onmessage = (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if ((m.event === "observation" || m.event === "alert") && state.view === "home") go("home");
  };
  ws.onclose = () => setTimeout(connectWS, 4000);
}

window.go = go;

// ---------- start ----------
if (state.token) boot().catch(showLogin); else showLogin();
