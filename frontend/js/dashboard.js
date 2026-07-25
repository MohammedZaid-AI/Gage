"use strict";

// --- helpers ---
const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => (r.ok ? r.json() : Promise.reject(r)));
const fmt = (v, unit) => (v === null || v === undefined ? "—" : `${(+v).toFixed(1)}${unit}`);
const imgUrl = (p) => (p ? "/" + p.replace(/^\/+/, "") : null);

// Demo session, filled by loadState(). ponytail: replace with a real login screen in Phase 4.
const session = { token: null, farmId: null, nodeId: null };
const DEMO = { phone: "9999999999", password: "demo1234" };

const summaryOf = (o) => o.vision_summary || o.ai_summary || "No analysis.";

// --- rendering ---
function renderObservation(o) {
  const url = imgUrl(o.image_path);
  if (url) {
    const img = $("latest-image");
    img.src = url;
    img.style.display = "block";
    $("no-image").style.display = "none";
  }
  $("latest-summary").textContent = summaryOf(o);
  $("m-temp").textContent = fmt(o.temperature, " °C");
  $("m-hum").textContent = fmt(o.humidity, " %");
  $("m-soil").textContent = fmt(o.soil_moisture, " %");
  $("m-gps").textContent =
    o.gps_lat != null && o.gps_long != null ? `${(+o.gps_lat).toFixed(4)}, ${(+o.gps_long).toFixed(4)}` : "—";
}

function addHistory(o, prepend = true) {
  const list = $("history-list");
  const empty = list.querySelector(".muted");
  if (empty) empty.remove();
  const li = document.createElement("li");
  const ts = new Date(o.timestamp).toLocaleTimeString();
  li.innerHTML = `<span class="ts">${ts}</span> — ${summaryOf(o)}`;
  if (prepend) list.prepend(li);
  else list.append(li);
}

function addChat(text, who) {
  const log = $("chat-log");
  const div = document.createElement("div");
  div.className = "msg " + who;
  div.textContent = text;
  log.append(div);
  log.scrollTop = log.scrollHeight;
}

let obsCount = 0;
function bumpCount() {
  obsCount += 1;
  $("m-count").textContent = obsCount;
}

// --- initial load ---
async function login() {
  const r = await api("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(DEMO),
  });
  session.token = r.access_token;
}

async function loadState() {
  try {
    await login();
  } catch (e) {
    console.error("demo login failed", e);
  }
  try {
    const s = await api("/api/state");
    session.farmId = s.farm && s.farm.id;
    session.nodeId = s.node_id;
    $("farm-badge").textContent = `Farm: ${s.farm ? s.farm.name : "—"}`;
    $("node-badge").textContent = `Node: ${s.node_id || "—"}`;
    obsCount = s.observation_count || 0;
    $("m-count").textContent = obsCount;
    if (s.latest_observation) renderObservation(s.latest_observation);
    (s.history || []).forEach((o) => addHistory(o, false));
  } catch (e) {
    console.error("state load failed", e);
  }
}

// --- websocket live updates ---
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const { event, data } = JSON.parse(ev.data);
    if (event === "observation") {
      renderObservation(data);
      addHistory(data);
      bumpCount();
    }
    // chat answers render from the POST response, not WS, to avoid double display.
  };
  ws.onclose = () => setTimeout(connectWS, 2000); // auto-reconnect
}

// --- actions ---
$("btn-capture").onclick = () => $("file-input").click();
$("file-input").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  if (!session.nodeId) return alert("No node available yet.");
  const fd = new FormData();
  fd.append("node_id", session.nodeId);
  fd.append("image", file);
  // ponytail: dashboard-side demo sensors. The phone/ESP32 sends real values in the field.
  fd.append("temperature", (24 + Math.random() * 6).toFixed(1));
  fd.append("humidity", (55 + Math.random() * 20).toFixed(1));
  fd.append("soil_moisture", (30 + Math.random() * 25).toFixed(1));
  navigator.geolocation?.getCurrentPosition(
    (pos) => sendObservation(fd, pos.coords),
    () => sendObservation(fd, null)
  );
  e.target.value = "";
};

async function sendObservation(fd, coords) {
  if (coords) {
    fd.append("gps_lat", coords.latitude);
    fd.append("gps_long", coords.longitude);
  }
  try {
    await fetch("/observations", { method: "POST", body: fd });
  } catch (err) {
    alert("Upload failed");
  }
}

$("chat-form").onsubmit = async (e) => {
  e.preventDefault();
  const input = $("chat-input");
  const q = input.value.trim();
  if (!q) return;
  if (!session.token || !session.farmId) return addChat("Session not ready.", "bot");
  addChat(q, "user");
  input.value = "";
  try {
    const r = await api("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify({ farm_id: session.farmId, question: q }),
    });
    addChat(r.answer, "bot");
  } catch {
    addChat("Sorry, the assistant is unavailable.", "bot");
  }
};

loadState();
connectWS();
