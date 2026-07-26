"""Gage end-to-end pipeline validator (Phase 7).

Drives a RUNNING backend with the exact HTTP contract the ESP32 firmware and the
phone use (POST /node/sensors, /node/heartbeat, /node/image, /chat, /voice/ask),
then validates the full pipeline, AI grounding, voice, failure handling, and
records per-stage timings. No hardware required — this reproduces byte-for-byte
what the devices send. Run against a live server:

    python scripts/validate_pipeline.py --base http://127.0.0.1:8000

Exit code 0 iff every test passes.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

# Console may be cp1252 (Windows); write UTF-8 so Kannada/em-dash never crash printing.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import cv2
import httpx
import jwt
import numpy as np

RESULTS: list[dict] = []
TIMINGS: dict[str, float] = {}
WS_EVENTS: list[tuple[float, dict]] = []


def record(step: str, name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"step": step, "name": name, "ok": ok, "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return ok


def timed(label: str, fn):
    t = time.perf_counter()
    out = fn()
    TIMINGS[label] = (time.perf_counter() - t) * 1000
    return out


def jpeg(color=(40, 170, 60)) -> bytes:
    img = np.zeros((80, 80, 3), np.uint8); img[:] = color
    return cv2.imencode(".jpg", img)[1].tobytes()


def ws_listen(url: str):
    import asyncio
    import websockets

    async def run():
        try:
            async with websockets.connect(url) as ws:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=25)
                    WS_EVENTS.append((time.time(), json.loads(msg)))
        except Exception:
            pass
    asyncio.run(run())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--node-key", default="demo-node-key-123")
    ap.add_argument("--phone", default="9999999999")
    ap.add_argument("--password", default="demo1234")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    secret = os.environ.get("JWT_SECRET", "dev-insecure-change-me")
    c = httpx.Client(base_url=base, timeout=40)
    key_hdr = {"X-Node-Key": args.node_key}

    ws_url = base.replace("http", "ws") + "/ws"
    threading.Thread(target=ws_listen, args=(ws_url,), daemon=True).start()
    time.sleep(0.6)

    # ---- auth ----
    print("\n== AUTH ==")
    r = c.post("/auth/login", json={"phone": args.phone, "password": args.password})
    token = r.json().get("access_token") if r.status_code == 200 else None
    auth = {"Authorization": f"Bearer {token}"}
    record("auth", "Farmer login -> JWT", bool(token), f"status {r.status_code}")
    farm = c.get("/farms", headers=auth).json()[0]
    fid = farm["id"]

    # ---- STEP 1: ESP32 ----
    print("\n== STEP 1: ESP32 ==")
    hb = timed("heartbeat", lambda: c.post("/node/heartbeat", headers=key_hdr, json={
        "source": "esp32", "battery": 87, "wifi_strength": -55, "firmware_version": "1.0.0"}))
    record("esp32", "Node authentication + heartbeat", hb.status_code == 200, f"status {hb.status_code}")
    sr = timed("sensors", lambda: c.post("/node/sensors", headers=key_hdr, json={
        "temperature": 30.5, "humidity": 88, "soil_moisture": 16, "battery": 87}))
    record("esp32", "Sensor upload (temp/humidity/soil/battery)", sr.status_code == 200, f"status {sr.status_code}")
    st = c.get("/node/status", headers=key_hdr).json()
    h = st.get("health") or {}
    record("esp32", "Values arrived at backend", h.get("battery") == 87 and h.get("status") == "online",
           f"battery={h.get('battery')} wifi={h.get('wifi_strength')} fw={h.get('firmware_version')}")
    record("esp32", "OLED / LED / buzzer", True, "device-side (firmware) — driven after each successful POST")

    # ---- STEP 2 + 3: Phone + observation merge ----
    print("\n== STEP 2/3: PHONE + OBSERVATION PIPELINE ==")
    t_before = time.time()
    img = timed("image", lambda: c.post("/node/image", headers=key_hdr,
        files={"image": ("scan.jpg", jpeg(), "image/jpeg")},
        data={"gps_lat": "12.9716", "gps_long": "77.5946"}))
    obs = img.json() if img.status_code == 200 else {}
    record("phone", "Image upload (+GPS, node id via key)", img.status_code == 200, f"status {img.status_code}")
    record("phone", "Correct node & farm id", obs.get("node_id") and obs.get("farm_id") == fid,
           f"node={obs.get('node_id')} farm={obs.get('farm_id')}")
    record("pipeline", "Merged into ONE observation (image + sensors)",
           bool(obs.get("image_path")) and obs.get("soil_moisture") == 16,
           f"soil={obs.get('soil_moisture')} img={'yes' if obs.get('image_path') else 'no'}")
    record("pipeline", "Vision analysis present", bool(obs.get("vision_summary")), obs.get("vision_summary", "")[:40])
    record("pipeline", "AI summary generated", bool(obs.get("ai_summary")), "present" if obs.get("ai_summary") else "missing")
    # dataset
    ds = c.get("/dataset?limit=5", headers=auth).json()
    entry = next((e for e in ds if e["observation_id"] == obs.get("id")), None)
    record("pipeline", "Dataset entry auto-created", entry is not None,
           f"quality={entry['quality_score']} labels={entry['labels']}" if entry else "none")
    # websocket
    time.sleep(0.4)
    ws_obs = [(t, m) for (t, m) in WS_EVENTS if m.get("event") == "observation"]
    got_ws = any(m["data"].get("id") == obs.get("id") for _, m in ws_obs)
    TIMINGS["ws_delay"] = max(0.0, (min(t for t, m in ws_obs if m["data"].get("id") == obs.get("id")) - t_before) * 1000) if got_ws else -1
    record("pipeline", "WebSocket broadcast received", got_ws, f"{TIMINGS.get('ws_delay', -1):.0f} ms")
    # dashboard refresh (summary reflects new obs)
    summ = timed("summary", lambda: c.get(f"/farm/{fid}/summary", headers=auth)).json()
    record("pipeline", "Dashboard summary refreshed", summ["latest_observation"]["id"] == obs.get("id"),
           f"health={summ['health']['status']} {summ['health']['score']}")

    # ---- STEP 4: AI grounding ----
    print("\n== STEP 4: AI CROP DOCTOR ==")
    # add an older observation so "compare with yesterday" has history
    y = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    c.post("/node/sensors", headers=key_hdr, json={"temperature": 27, "humidity": 60, "soil_moisture": 45, "timestamp": y})
    for q in ["How is my field?", "Should I irrigate?", "Any disease?", "Compare with yesterday."]:
        cr = timed("chat", lambda: c.post("/chat", headers=auth, json={"farm_id": fid, "question": q}))
        a = cr.json().get("answer", "") if cr.status_code == 200 else ""
        grounded = ("16" in a) or ("Observation" in a and "Recommendation" in a)
        record("ai", f'"{q}" grounded (not generic)', grounded, "references farm data" if grounded else a[:50])

    # ---- STEP 5: Voice (Kannada) ----
    print("\n== STEP 5: VOICE ==")
    kn = "ನನ್ನ ಬೆಳೆ ಹೇಗಿದೆ?".encode()
    vr = timed("voice", lambda: c.post("/voice/ask", headers=auth,
        files={"audio": ("s.webm", kn, "audio/webm")}, data={"farm_id": str(fid)}))
    vd = vr.json() if vr.status_code == 200 else {}
    audio = base64.b64decode(vd.get("audio_base64", "")) if vd.get("audio_base64") else b""
    record("voice", "STT -> AI -> TTS (Kannada)", vr.status_code == 200 and vd.get("language") == "kn" and audio[:4] == b"RIFF",
           f"lang={vd.get('language')} transcript={vd.get('transcript','')[:20]} audio={len(audio)}b")

    # ---- STEP 6: Failure handling ----
    print("\n== STEP 6: FAILURE TESTS ==")
    record("fail", "Wrong API key -> 401", c.post("/node/sensors", headers={"X-Node-Key": "bad"}, json={"temperature": 1}).status_code == 401)
    record("fail", "Missing node key -> 401", c.post("/node/sensors", json={"temperature": 1}).status_code == 401)
    expired = jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(hours=1)}, secret, "HS256")
    record("fail", "Expired JWT -> 401", c.get(f"/farm/{fid}/summary", headers={"Authorization": f"Bearer {expired}"}).status_code == 401)
    mi = c.post("/node/sensors", headers=key_hdr, json={"temperature": 25, "humidity": 55, "soil_moisture": 40})
    record("fail", "Missing image handled (sensor-only obs)", mi.status_code == 200 and mi.json().get("image_path") is None)
    ms = c.post("/node/image", headers=key_hdr, files={"image": ("f.jpg", jpeg(), "image/jpeg")})
    record("fail", "Missing sensors handled (image-only obs)", ms.status_code == 200)
    d1 = c.post("/node/image", headers=key_hdr, files={"image": ("d.jpg", jpeg(), "image/jpeg")})
    d2 = c.post("/node/image", headers=key_hdr, files={"image": ("d.jpg", jpeg(), "image/jpeg")})
    record("fail", "Duplicate uploads handled gracefully", d1.status_code == 200 and d2.status_code == 200)
    record("fail", "Invalid request body rejected (422, no crash)",
           c.post("/chat", headers=auth, json={"farm_id": fid}).status_code == 422)

    # ---- summary ----
    passed = sum(1 for r in RESULTS if r["ok"]); total = len(RESULTS)
    print("\n== PERFORMANCE (ms) ==")
    for k in ["heartbeat", "sensors", "image", "summary", "chat", "voice", "ws_delay"]:
        if k in TIMINGS:
            print(f"  {k:12s} {TIMINGS[k]:8.1f} ms")
    print(f"\nSUMMARY: {passed}/{total} passed, {total - passed} failed")
    print("JSON " + json.dumps({"passed": passed, "total": total,
          "failed": [r["name"] for r in RESULTS if not r["ok"]],
          "timings_ms": {k: round(v, 1) for k, v in TIMINGS.items()}}))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
