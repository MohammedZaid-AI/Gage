"use strict";

// --- helpers ---
const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => (r.ok ? r.json() : Promise.reject(r)));
const fmt = (v, unit) => (v === null || v === undefined ? "—" : `${(+v).toFixed(1)}${unit}`);
const imgUrl = (p) => (p ? "/" + p.replace(/^\/+/, "") : null);

// Demo session, filled by loadState(). ponytail: replace with a real login screen in Phase 4.
const session = { token: null, farmId: null, nodeId: null, nodeKey: null };
const DEMO = { phone: "9999999999", password: "demo1234" };

const summaryOf = (o) => o.ai_summary || o.vision_summary || "No analysis.";
const ago = (iso) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s | 0}s ago`;
  if (s < 3600) return `${(s / 60) | 0}m ago`;
  return `${(s / 3600) | 0}h ago`;
};

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

function nodeLabel(h) {
  if (!h) return { text: "UNKNOWN", cls: "off" };
  if (h.status === "offline") return { text: "OFFLINE", cls: "off" };
  if (h.battery != null && h.battery < 20) return { text: "LOW BATTERY", cls: "warn" };
  return { text: "ONLINE", cls: "on" };
}

function renderNodes(nodes) {
  const list = $("node-list");
  list.innerHTML = "";
  if (!nodes || !nodes.length) {
    list.innerHTML = '<li class="muted">No nodes yet.</li>';
    return;
  }
  for (const n of nodes) {
    const h = n.health || {};
    const badge = nodeLabel(n.health);
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="node-name">${n.name || n.id}</span> ` +
      `<span class="badge ${badge.cls}">${badge.text}</span>` +
      `<div class="node-meta">Battery ${fmt(h.battery, "%")} · ` +
      `Signal ${h.wifi_strength != null ? h.wifi_strength + " dBm" : "—"} · ` +
      `Seen ${ago(h.last_seen)} · fw ${h.firmware_version || "—"}</div>`;
    list.append(li);
  }
}

function renderAlerts(alerts) {
  const list = $("alert-list");
  list.innerHTML = "";
  if (!alerts || !alerts.length) {
    list.innerHTML = '<li class="muted">No alerts.</li>';
    return;
  }
  for (const a of alerts) addAlert(a, false);
}

function addAlert(a, prepend = true) {
  const list = $("alert-list");
  const empty = list.querySelector(".muted");
  if (empty) empty.remove();
  const li = document.createElement("li");
  li.className = "alert-item " + (a.severity === "critical" ? "crit" : "warn");
  li.innerHTML = `<span class="ts">${ago(a.created_at)}</span> ${a.message}`;
  if (prepend) list.prepend(li);
  else list.append(li);
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

async function fetchNodeKey() {
  // The farmer owns the node and needs its api_key to provision/simulate the device.
  const nodes = await api(`/farms/${session.farmId}/nodes`, {
    headers: { Authorization: `Bearer ${session.token}` },
  });
  const n = nodes.find((x) => x.id === session.nodeId) || nodes[0];
  session.nodeKey = n && n.api_key;
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
    renderNodes(s.nodes);
    renderAlerts(s.alerts);
    if (session.token && session.farmId) await fetchNodeKey();
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
    } else if (event === "alert") {
      addAlert(data);
    } else if (event === "node_health") {
      loadState(); // cheap: refresh node panel from source of truth
    }
    // chat answers render from the POST response, not WS, to avoid double display.
  };
  ws.onclose = () => setTimeout(connectWS, 2000); // auto-reconnect
}

// --- actions ---
// Simulate a full capture: the ESP32 pushes sensors and the phone pushes an image;
// the backend merges them into one observation.
$("btn-capture").onclick = () => $("file-input").click();
$("file-input").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  if (!session.nodeKey) return alert("Node key not loaded yet.");
  const keyHeader = { "X-Node-Key": session.nodeKey };

  // 1) ESP32 sensors
  try {
    await fetch("/node/sensors", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...keyHeader },
      body: JSON.stringify({
        temperature: +(24 + Math.random() * 6).toFixed(1),
        humidity: +(55 + Math.random() * 20).toFixed(1),
        soil_moisture: +(30 + Math.random() * 25).toFixed(1),
        battery: 90,
      }),
    });
  } catch {
    /* non-fatal for the demo */
  }

  // 2) Phone image + GPS (merges into the observation created above)
  const fd = new FormData();
  fd.append("image", file);
  navigator.geolocation?.getCurrentPosition(
    (pos) => sendImage(fd, keyHeader, pos.coords),
    () => sendImage(fd, keyHeader, null)
  );
  e.target.value = "";
};

async function sendImage(fd, keyHeader, coords) {
  if (coords) {
    fd.append("gps_lat", coords.latitude);
    fd.append("gps_long", coords.longitude);
  }
  try {
    await fetch("/node/image", { method: "POST", headers: keyHeader, body: fd });
  } catch (err) {
    alert("Upload failed");
  }
}

// --- voice: record -> /voice/ask -> show transcript + answer -> speak answer ---
function speak(text, language) {
  if (!("speechSynthesis" in window) || !text) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = language === "kn" ? "kn-IN" : "en-IN"; // browser TTS for demo playback
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

let recorder = null;
let chunks = [];
async function toggleMic() {
  const btn = $("btn-mic");
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) return alert("Microphone not supported.");
  if (!session.token || !session.farmId) return alert("Session not ready.");
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    return alert("Microphone permission denied.");
  }
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    btn.classList.remove("on");
    btn.textContent = "🎤";
    const blob = new Blob(chunks, { type: "audio/webm" });
    const fd = new FormData();
    fd.append("farm_id", session.farmId);
    fd.append("audio", blob, "speech.webm");
    addChat("🎤 …", "user");
    try {
      const r = await api("/voice/ask", {
        method: "POST",
        headers: { Authorization: `Bearer ${session.token}` },
        body: fd,
      });
      $("chat-log").lastChild.textContent = "🎤 " + r.transcript;
      addChat(r.answer, "bot");
      speak(r.answer, r.language);
    } catch {
      $("chat-log").lastChild.textContent = "🎤 (could not understand)";
    }
  };
  recorder.start();
  btn.classList.add("on");
  btn.textContent = "⏺";
}
$("btn-mic").onclick = toggleMic;

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
