# Connecting Real Hardware to Gage

The monitoring node is two independent devices talking to the backend over your
Wi‑Fi. The backend merges their data into one observation.

```
ESP32  --(temp/humidity/soil/battery)-->  POST /node/sensors     ┐
ESP32  --(heartbeat every 60s)-------->    POST /node/heartbeat    ├─ merged into ONE
Phone  --(image + GPS)---------------->    POST /node/image        ┘  observation (60s window)
```
Every request carries the header `X-Node-Key: <api_key>`. No key = rejected.

---

## Step 1 — Make the backend reachable on your Wi‑Fi (the #1 gotcha)

By default the server listens only on `127.0.0.1` (your PC's localhost). Your
ESP32 and phone are *other devices* — they can't reach `127.0.0.1`. Bind to all
interfaces instead:

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Find your PC's LAN IP (the address the devices will use):
- Windows: `ipconfig` → look for **IPv4 Address** under your Wi‑Fi adapter, e.g. `192.168.1.42`.

So your backend URL for the devices is `http://192.168.1.42:8000` (use YOUR ip).

Checklist:
- PC, ESP32, and phone are all on the **same Wi‑Fi network**.
- **Windows Firewall**: the first time, allow Python/uvicorn on **Private networks**
  (a prompt appears), or add an inbound rule for TCP port 8000.
- Test from the phone's browser: open `http://192.168.1.42:8000` — you should see
  the Gage app. If that loads, the devices can reach it.

---

## Step 2 — Get a node API key

Option A (quick test): use the seeded demo node — id `demo-node-1`, key
`demo-node-key-123`.

Option B (real node): in the app → **Settings → Monitoring nodes**, type a node id
(e.g. `field-node-1`) and **Register**. Its **api_key** is shown there — copy it.

---

## Step 3 — Flash the ESP32

Firmware: `firmware/esp32_node.ino` (Arduino IDE, board = your ESP32 dev module).

Install these libraries (Library Manager): **DHT sensor library** (Adafruit),
**Adafruit SSD1306**, **Adafruit GFX**. `WiFi.h` / `HTTPClient.h` ship with the
ESP32 core.

Edit the config block at the top of the sketch:
```cpp
const char* WIFI_SSID = "your-wifi";              // your Wi‑Fi name
const char* WIFI_PASS = "your-pass";              // your Wi‑Fi password
const char* BACKEND   = "http://192.168.1.42:8000"; // your PC's LAN IP from Step 1
const char* NODE_KEY  = "demo-node-key-123";      // the api_key from Step 2
```
Upload. Open the Serial Monitor (115200 baud) to watch it connect and POST. The
OLED shows Wi‑Fi status and the latest readings; the buzzer beeps on a failed POST.

---

## Step 4 — Wire the sensors (pins are in the sketch)

| Part | ESP32 pin |
|------|-----------|
| DHT22 data | GPIO 4 |
| Soil moisture (analog out) | GPIO 34 |
| OLED SSD1306 (I²C) | SDA 21, SCL 22 |
| Status LED | GPIO 2 |
| Buzzer | GPIO 15 |

Power the DHT22 and soil sensor from 3V3 + GND. (Change the pins in the sketch if
your wiring differs.)

**Calibrate the soil probe once** — this matters, every probe differs:
1. Hold the probe in **dry air**, read the raw ADC in Serial → set `SOIL_DRY`.
2. Put it in a **cup of water**, read the raw ADC → set `SOIL_WET`.
Re-flash. Now 0 % = dry air, 100 % = water.

---

## Step 5 — The phone (image + GPS)

There is no separate native app yet — the phone participates through the **web app**:
1. On the phone's browser open `http://192.168.1.42:8000` and log in.
2. On **Home**, tap **📷 Scan Crop** → allow camera + location → it captures a photo
   and posts it (with GPS) to `/node/image` using the node's key.

The backend merges that image with the ESP32's most recent sensor reading (within
60 s) into one observation, runs vision on the image, and updates the dashboard.

> Note: Scan Crop currently also sends *demo* sensor values (so it works with no
> ESP32). Once your ESP32 is sending **real** sensors, tell me and I'll switch Scan
> Crop to send the image only — a one-line change — so the real readings are used.

> **Secure-context caveat (important):** over plain `http://<LAN-ip>:8000`, mobile
> browsers **block the microphone and GPS** (those need HTTPS or localhost). So on
> the phone: the **camera photo works**, but **GPS is skipped** and **voice (mic)
> won't record**. Sensors/image/AI/dashboard all work fine over HTTP. To get mic +
> GPS on the phone, serve over HTTPS — easiest is a tunnel like `cloudflared`/`ngrok`
> (gives an https URL), or run the browser on the PC at `localhost` where they work.
> The ESP32 is unaffected (it's not a browser; plain HTTP is fine).

---

## Step 6 — Verify it end to end

Watch the server log — you'll see each stage:
```
node connected: heartbeat from demo-node-1 ...
sensors merged into observation <id> ...
vision completed for observation <id>
AI summary generated for observation <id>
dataset entry for obs <id> ...
dashboard updated: broadcast 'observation' -> N client(s)
```
On the dashboard: Home shows the live sensor cards + node **Online** + battery,
Timeline shows the new scan, and the health score updates. Ask Gage will now be
grounded in your real field data.

### Troubleshooting
- **Device can't connect / timeout** → server not on `0.0.0.0`, wrong PC IP, different
  Wi‑Fi, or firewall blocking port 8000.
- **401 from the node** → wrong/missing `X-Node-Key`.
- **404 unknown node** → the node id/key isn't registered (do Step 2).
- **Readings look wrong** → recalibrate the soil probe (Step 4); check DHT22 wiring.
- **No image analysis** → the phone image didn't upload; check the phone can reach the
  backend URL and that location/camera permissions were granted.
