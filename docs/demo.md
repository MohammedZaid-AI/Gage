# Gage — Demo Checklist

A step-by-step checklist to run a full end-to-end demo of Gage, from monitoring
node to grounded farmer response.

## 0. Prerequisites
- Python deps installed: `pip install -r requirements.txt`
- `.env` present (copy from `.env.example`). For an **offline / keyless demo** set
  `LLM_PROVIDER=mock` and `SPEECH_PROVIDER=mock`. For the **real** assistant set
  `LLM_PROVIDER=groq` + `GROQ_API_KEY`, and (optional voice) `SPEECH_PROVIDER=sarvam` + `SARVAM_API_KEY`.
- Fresh dev DB after any schema change (no Alembic yet — `create_all` adds tables but
  not columns, so an old DB drifts and 500s like `no such column: farms.crop_type`):
  **stop the server**, then `python scripts/reset_dev_db.py` (backs up the old DB to
  `storage/observations.db.bak-*`, recreates the schema, re-seeds), then restart.

## Live demo checklist

| # | Step | How to verify | ✅ |
|---|------|---------------|----|
| 1 | **Backend running** | `python -m uvicorn backend.main:app --reload` → open http://127.0.0.1:8000 | ☐ |
| 2 | **Farmer login** | Dashboard login (demo: phone `9999999999` / `demo1234`) → lands on Home | ☐ |
| 3 | **ESP32 connected** | Power the node; it POSTs `/node/heartbeat`. Home shows Node **Online** + battery | ☐ |
| 4 | **Phone connected** | Open the app on the phone; camera + GPS permission granted | ☐ |
| 5 | **Sensors working** | ESP32 POSTs `/node/sensors`; values appear in Live Conditions | ☐ |
| 6 | **Image upload working** | Tap **Scan Crop** (or phone auto-capture) → `/node/image` 200 | ☐ |
| 7 | **Observation merge working** | Sensors + image within 60s become **one** observation (Timeline shows a single card) | ☐ |
| 8 | **Vision working** | Observation detail shows a Vision Summary | ☐ |
| 9 | **Dashboard updated** | Home health/sensors/latest-scan refresh (WebSocket "Analyzing…" banner) | ☐ |
| 10 | **Voice working** | Ask Gage → tap mic, speak Kannada/English → spoken answer | ☐ |
| 11 | **AI answer grounded** | Answer references *this* farm's readings (Observation/Analysis/Confidence/Recommendations) — never generic | ☐ |
| 12 | **Health score updated** | Home gauge reflects soil/humidity/temp/alerts | ☐ |
| 13 | **Dataset entry created** | Settings/Reports show record count increasing; `/dataset/stats` grows | ☐ |
| 14 | **WebSocket working** | New capture animates Home without a manual refresh | ☐ |
| 15 | **End-to-end demo passed** | Node → merge → vision → AI → voice → dashboard, all observed | ☐ |

## One-command pipeline validation (no hardware)
Reproduces exactly what the ESP32 + phone send and checks every stage, AI
grounding, voice, failure handling, and timings:

```bash
# terminal 1
python -m uvicorn backend.main:app --port 8000
# terminal 2
python scripts/validate_pipeline.py --base http://127.0.0.1:8000
```
Exit code `0` = all checks passed. See `docs/validation_report.md` for a captured run.

## Node provisioning (real hardware)
1. In **Settings → Monitoring nodes**, register a node id; copy its **api_key**.
2. Flash `firmware/esp32_node.ino` with your Wi-Fi creds, backend URL, and that `NODE_KEY`.
3. Calibrate the soil probe once (`SOIL_DRY` / `SOIL_WET` in the sketch).
4. The phone app posts images to `/node/image` with the same node key.
