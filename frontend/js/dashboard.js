"use strict";

// --- helpers ---
const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => (r.ok ? r.json() : Promise.reject(r)));
const fmt = (v, unit) => (v === null || v === undefined ? "—" : `${(+v).toFixed(1)}${unit}`);
const imgUrl = (p) => (p ? "/" + p.replace(/^\/+/, "") : null);

function toast(msg) {
  console.log(msg);
}

// --- rendering ---
function setInspection(insp) {
  const badge = $("inspection-badge");
  if (insp && !insp.ended_at) {
    badge.textContent = `Inspection #${insp.id}: active`;
    badge.className = "badge on";
  } else {
    badge.textContent = "Inspection: idle";
    badge.className = "badge off";
  }
  if (insp && insp.total_observations != null) $("m-count").textContent = insp.total_observations;
}

function setRobot(r) {
  const badge = $("robot-badge");
  const online = r && r.online;
  const cmd = r && r.last_command ? ` · ${r.last_command}` : "";
  badge.textContent = `Robot: ${online ? "online" : "offline"}${cmd}`;
  badge.className = "badge " + (online ? "on" : "off");
}

function renderObservation(o) {
  const url = imgUrl(o.image_path);
  if (url) {
    const img = $("latest-image");
    img.src = url;
    img.style.display = "block";
    $("no-image").style.display = "none";
  }
  $("latest-summary").textContent = o.ai_summary || "No analysis.";
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
  li.innerHTML = `<span class="ts">${ts}</span> — ${o.ai_summary || "observation"}`;
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
async function loadState() {
  try {
    const s = await api("/api/state");
    setRobot(s.robot);
    setInspection(s.inspection);
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
    } else if (event === "inspection") {
      setInspection(data);
    } else if (event === "robot") {
      setRobot(data);
    }
    // chat answers render from the POST response, not WS, to avoid double display.
  };
  ws.onclose = () => setTimeout(connectWS, 2000); // auto-reconnect
}

// --- actions ---
$("btn-start").onclick = () => api("/inspections/start", { method: "POST" }).catch(() => alert("Already active?"));
$("btn-stop").onclick = () => api("/inspections/stop", { method: "POST" }).catch(() => alert("No active inspection."));
$("btn-estop").onclick = () => api("/robot/stop", { method: "POST" });

document.querySelectorAll(".btn.move").forEach((b) => {
  b.onclick = () => api(`/robot/${b.dataset.cmd}`, { method: "POST" });
});

// Capture: use the device camera (phone) or a file, then upload with sensor readings.
$("btn-capture").onclick = () => $("file-input").click();
$("file-input").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
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
  addChat(q, "user");
  input.value = "";
  try {
    const r = await api("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    addChat(r.answer, "bot");
  } catch {
    addChat("Sorry, the assistant is unavailable.", "bot");
  }
};

loadState();
connectWS();
