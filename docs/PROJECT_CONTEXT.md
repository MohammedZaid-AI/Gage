# Gage — Full Project Context

> Handoff document. Everything another AI assistant (or engineer) needs to work on this
> project without reading the whole codebase. Current as of commit `71a641a`.

---

## 1. What Gage is

**An AI-powered, multilingual (Kannada + English) agricultural field assistant for
sugarcane farmers in Karnataka, India.**

It is being built as a **production product**, not a hackathon demo — intended to be
deployable across thousands of farms. It is also the intended entry for **Smart India
Hackathon (SIH)**.

The product has two halves:

1. **The AI Assistant** (what the farmer uses) — answers questions about their field,
   grounded strictly in that field's own measured data, in the farmer's language, by
   voice or text.
2. **Low-cost Monitoring Nodes** (the data infrastructure) — ESP32 + an Android phone.
   These are *not* the product; they are the data moat. Every deployed node makes the AI
   better. The founder's framing: **"the Tesla fleet-data analogy."**

### The core design principle

The assistant must **never hallucinate about a farm**. Every answer is grounded in that
farm's own observations. If evidence is thin it must say so rather than guess. This
constraint drives most of the architecture.

---

## 2. Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy 2.0 (typed `Mapped[]`), Pydantic v2 + pydantic-settings |
| Database | SQLite (dev) — `storage/observations.db`; Postgres-ready |
| Auth | JWT (PyJWT, HS256) + bcrypt, phone + password |
| LLM | **Groq**, model `openai/gpt-oss-120b` (OpenAI-compatible API via `openai` SDK) |
| Speech | **Sarvam AI** — STT `saarika:v2.5`, TTS `bulbul:v2`, speaker `anushka` |
| Vision | **Not yet real** — heuristic mock only (see §7) |
| Frontend | Vanilla HTML/CSS/JS SPA. No React, no build step. |
| Realtime | WebSocket (`/ws`) |
| Hardware | ESP32 + DHT22 + capacitive soil probe + SSD1306 OLED |
| Python | 3.14 (global install; **no venv exists** — run with plain `python`) |

**No Alembic.** Schema changes are handled by `create_all` plus a custom
`_sync_missing_columns()` self-heal in `backend/database.py` that `ALTER TABLE ADD
COLUMN`s any model column missing from an existing table. Non-destructive; skips NOT NULL
(SQLite cannot add those).

---

## 3. Repository layout

```
backend/
  main.py               FastAPI app, static mounts, router registration, MIME fixes
  config.py             pydantic-settings Settings (all env vars)
  database.py           engine, session, init_db + _sync_missing_columns self-heal
  models.py             SQLAlchemy ORM entities
  schemas.py            Pydantic request/response models
  dependencies.py       get_current_farmer, owned_farm, get_node (X-Node-Key auth)
  realtime.py           WebSocket broadcast hub
  seed.py               demo farmer/farm/node seeding
  selftest.py           offline smoke test (16 checks, no server needed)
  core/security.py      JWT + bcrypt

  ai/
    base.py             Provider ABCs + VisionResult + class vocabulary
    service.py          Provider selection facade (analyze_image/complete/transcribe/synthesize)
    mock.py             Offline providers (OpenCV colour stats, templated LLM, silent WAV)
    knowledge.py        Curated sugarcane knowledge base + keyword retrieval (the RAG)
    prompt_builder.py   THE ONLY place farm data becomes prompt text
    orchestrator.py     answer() pipeline: context -> retrieve -> prompt -> LLM -> persist
    providers/
      groq_provider.py    Groq LLM
      sarvam_provider.py  Sarvam STT + TTS

  services/
    farm_context.py     Farm Context Engine — assembles ALL AI context (+ trends)
    health_score.py     Rule-based 0-100 farm health
    alerts.py           Threshold alert engine with de-duplication
    observation_service.py  Sensor+image merge, vision, AI summary, dataset feed

  dataset/              The Dataset Builder (independent of the AI)
    models.py           DatasetEntry, DatasetExport
    quality.py          QualityScorer — 0-100 training-usefulness score
    labels.py           LabelGenerator — deterministic auto-labels (negation-aware)
    exporter.py         JSONL / CSV / Parquet, versioned + SHA-256 checksummed
    repository.py, service.py, schemas.py, validators.py

  routers/              auth, farm, farm_intel, node, observation, chat, voice, dataset

frontend/
  dashboard.html        Single page shell
  css/style.css         Design system (see §9)
  js/dashboard.js       Whole SPA: router, views, icons, voice, WebSocket

firmware/esp32_node.ino ESP32 reference sketch
scripts/                validate_pipeline.py (25 e2e checks), reset_dev_db.py
docs/                   demo.md, hardware.md, validation_report.md
storage/                observations.db, images/, datasets/   (gitignored)
```

Roughly 3,900 LOC Python + ~1,000 LOC frontend.

---

## 4. Database schema

| Table | Key columns |
|---|---|
| `farmers` | id, phone (unique), password_hash, name, language, created_at |
| `farms` | id, farmer_id→farmers, name, crop_type, village, area_acres |
| `nodes` | **id (str, device id, PK)**, farm_id, name, **api_key (unique)**, location |
| `node_health` | node_id, status (online/offline), last_seen, battery, wifi_strength, firmware_version, gps/camera/storage_available |
| `node_heartbeats` | id, node_id, source, battery, wifi, firmware, capabilities, timestamp |
| `sensor_readings` | id, node_id, farm_id, temperature, humidity, soil_moisture, battery, timestamp, observation_id |
| `observations` | **id (uuid hex, PK)**, farm_id, node_id, timestamp, gps_lat/long, image_path, temperature, humidity, soil_moisture, **vision_summary, vision_label, vision_confidence**, ai_summary |
| `alerts` | id, farm_id, node_id, type, severity, message, value, resolved, created_at |
| `conversations` | id, farm_id, farmer_id, question, answer, language, timestamp |
| `dataset_entries` | observation_id (unique), farm/node/crop, timestamp, gps, sensors, vision_summary, ai_summary, image_path, **active_alerts (JSON), labels (JSON), quality_score, quality_reason, status** |
| `dataset_exports` | dataset_version (unique), fmt, record_count, filters_used (JSON), **checksum (sha256)**, path |

**Relationships:** Farmer 1─N Farm 1─N Node 1─N Observation. Multi-tenant: every read is
scoped through `owned_farm()`, so a farmer can only ever see their own farms.

---

## 5. API surface

**Auth** (`Authorization: Bearer <jwt>`)

- `POST /auth/register`, `POST /auth/login` → `{access_token}` · `GET /auth/me`

**Farms and nodes**

- `POST /farms`, `GET /farms`
- `POST /farms/{farm_id}/nodes` (returns generated `api_key`), `GET /farms/{farm_id}/nodes`

**Farm intelligence**

- `GET /farm/{farm_id}/summary` — health, sensor snapshot, latest observation, trends, active alerts, AI summary
- `GET /farm/{farm_id}/timeline?limit=` · `GET /farm/{farm_id}/health`

**Node ingest** (auth via **`X-Node-Key`** header, NOT JWT)

- `POST /node/sensors` — body `{temperature, humidity, soil_moisture, battery, timestamp}`, all optional floats. The node is identified by the header, not the body.
- `POST /node/image` — multipart `image` + optional `gps_lat`, `gps_long`
- `POST /node/heartbeat` · `GET /node/status` · `GET /node/history`

**AI**

- `POST /chat` — `{farm_id, question}` → `{answer, language}`
- `POST /voice/ask` — multipart `farm_id` + `audio` → `{transcript, answer, language, audio_base64}`
- `POST /voice/speak` — `{text, language}` → `{audio_base64}`

**Dataset**

- `GET /dataset`, `GET /dataset/stats`, `GET /dataset/{entry_id}`, `POST /dataset/export`

**Other:** `GET /` dashboard · `WS /ws` live updates · `/static/*`

---

## 6. How the AI pipeline works

```
Question
  ↓
FarmContext.build()      ← the ONE place farm data is assembled
  ↓  (farmer, farm, crop, latest + 10 recent observations, latest sensor
  ↓   reading, active alerts, last 5 conversations, computed trends)
knowledge.retrieve()     ← keyword RAG over curated sugarcane KB
  ↓
prompt_builder.build()   ← THE ONLY place farm data becomes prompt text
  ↓
LLMProvider.answer()     ← Groq (or mock)
  ↓
persist Conversation     ← becomes memory for the next question
```

### The response contract (in `prompt_builder.py`)

Every answer must use exactly four sections:

- **Observation** — observed facts only (numbers, vision, alerts). No interpretation.
- **Analysis** — inference, kept strictly separate from the facts.
- **Confidence** — exactly High / Medium / Low with a one-line reason.
- **Recommendations** — Immediate actions / Monitoring / When to seek expert help.

**Hard rules enforced in the prompt:**

- Never mix Observed Facts, Inference, and Recommendation.
- If evidence is insufficient, reply exactly *"I don't have enough evidence from the
  latest observation."* and name what is missing. **Do not guess.**
- Active alerts are addressed first.
- If vision and sensors disagree, state the uncertainty rather than picking one.
- **Never name a disease if the image was not classified** (added with the vision refactor).
- Reply in the farmer's language.

### Observation merging

An image and a sensor reading from the same node within `merge_window_seconds` (60s)
become **ONE observation**. This is how a phone photo and ESP32 sensors combine into a
single labeled record.

### Provider abstraction

`ai/base.py` defines `VisionProvider`, `LLMProvider`, `SpeechProvider` ABCs. Selection is
by config in `ai/service.py`. **Mock-first**: every provider has an offline
implementation so the demo never breaks without API keys.

---

## 7. Current state of Vision — the most important gap

**There is no trained vision model yet.** `_select_vision()` always returns
`MockVisionProvider`, which does OpenCV HSV colour statistics: percentage of green,
percentage of yellow, mean brightness. **It cannot recognise anything.** It cannot tell
sugarcane from a water bottle.

**The abstention seam is built (commit `80da81b`)** so a trained model drops in cleanly:

```python
@dataclass(frozen=True)
class VisionResult:
    description: str              # prose for the LLM prompt, always present
    label: str | None = None      # populated only by a real classifier
    confidence: float | None = None
    abstained: bool = False       # True => do NOT diagnose from this image
    reason: str | None = None

DISEASE_CLASSES = ("healthy", "red_rot", "rust", "yellow_leaf", "mosaic", "leaf_spot")
NOT_CROP = "not_sugarcane"
```

- `VisionProvider.describe() -> str` became **`analyze() -> VisionResult`**.
- `MockVisionProvider` **abstains by construction** — counting green pixels is not a
  diagnosis, so it never presents itself as one.
- `Observation` gained `vision_label` + `vision_confidence`; an abstention leaves them
  NULL so nothing downstream can read "unknown" as "healthy".
- `labels.py`, `health_score.py`, `quality.py` now read the structured verdict instead of
  regexing the prose.

**Why `not_sugarcane` is a trained class, not a fallback:** a closed-set softmax always
names one of its classes with high confidence. "Is this even sugarcane?" must be
learnable, not inferred afterwards.

---

## 8. Hardware — the monitoring node

Two independent devices talking to the backend over Wi-Fi:

```
ESP32  --temp/humidity/soil/battery-->  POST /node/sensors    ┐
ESP32  --heartbeat every 60s-------->   POST /node/heartbeat   ├─ merged into ONE
Phone  --image + GPS--------------->    POST /node/image       ┘  observation (60s)
```

Every request carries `X-Node-Key: <api_key>`. No key = 401.

| Part | ESP32 pin |
|---|---|
| DHT22 data | GPIO 4 |
| Soil moisture (analog) | GPIO 34 |
| OLED SSD1306 (I²C) | SDA 21, SCL 22 |
| Status LED / Buzzer | GPIO 2 / GPIO 15 |

Sensor push every **30 s**, heartbeat every **60 s**. The soil probe needs one-time
calibration (`SOIL_DRY` in dry air, `SOIL_WET` in water). Estimated node BOM ≈ ₹900–1,200.

**Secure-context caveat:** over plain `http://<LAN-IP>`, mobile browsers **block the
microphone and GPS** (they need HTTPS or localhost). Camera and all data flow work fine
over HTTP. The ESP32 is unaffected — it is not a browser.

---

## 9. Frontend

Vanilla JS SPA — a "Farm Operating System" with five views: **Home, Timeline, Ask Gage,
Reports, Settings**, plus an observation Detail view.

Redesigned in commit `132df5d`:

- **28 stroke SVG icons on a 24px grid replace all emoji.** Static markup declares
  `data-icon="..."` and `hydrateIcons()` injects from the single icon set.
- Warm paper neutrals + one deep-green accent; each metric has its own hue.
- Tabular numerals so values don't jitter on live update.
- Health gauge is a **240° instrument dial** (a full ring read as a loading spinner);
  a 5-segment meter replaced a star rating.
- Full dark mode, `prefers-reduced-motion`, focus-visible rings.
- Soil moisture shows as **words** (Very dry / Dry / Moist / Wet / Saturated), not a %.
- Voice is **press-to-play** — each answer gets a Play button; nothing autoplays.
- `browserSpeak()` requires a voice whose language actually matches, so Kannada text is
  never spoken by an English voice.
- Assets are cache-busted with `?v=NN` — **bump this on every frontend change**.

---

## 10. Configuration (`.env`)

`.env` is **gitignored** and holds real keys. `.env.example` is tracked with empty
placeholders.

```
DATABASE_URL=sqlite:///./storage/observations.db
VISION_PROVIDER=mock            # only mock exists today
LLM_PROVIDER=groq               # mock | groq
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-120b  # NOTE the "openai/" prefix — required on Groq
SPEECH_PROVIDER=sarvam          # mock | sarvam
SARVAM_API_KEY=...
SARVAM_STT_MODEL=saarika:v2.5   # v2 was deprecated -> HTTP 400
SARVAM_TTS_MODEL=bulbul:v2
SARVAM_SPEAKER=anushka
JWT_SECRET=change-me
```

Alert thresholds (global for V1): `humidity_max=85%`, `soil_moisture_min=20%`,
`temperature_max=40C`, `low_battery_percent=20%`, `merge_window_seconds=60`,
`offline_seconds=180`, `seed_demo=true`.

---

## 11. Running it

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

- **PC:** `http://localhost:8080` ← use this; localhost is a secure context so the mic works
- **Phone / ESP32:** `http://<your-LAN-IP>:8080`
- `0.0.0.0` is a *bind wildcard*, **not a browsable address**.
- Port 8000 is occupied on the dev machine by an unrelated gateway process — hence 8080.
- Demo login: phone `9999999999`, password `demo1234`. Demo node key `demo-node-key-123`.

Tests: `python -m backend.selftest` (16 checks, offline — run with `LLM_PROVIDER=mock`)
and `python scripts/validate_pipeline.py` (25 end-to-end checks).

---

## 12. Honest assessment — strengths and gaps

### Genuinely strong

- **Farm Context Engine** — one immutable snapshot assembles all AI context; nothing else
  builds prompts. Real architecture.
- **Grounding contract** — facts/inference/confidence separated, explicit refusal path,
  conflict acknowledgement. Better than most production LLM systems.
- **Dataset Builder** — quality scoring, negation-aware deterministic auto-labels,
  versioned + checksummed exports. Rare at any level.
- **Provider abstraction** with mock-first fallbacks.
- Working Kannada voice loop, working hardware, clean multi-tenancy.

### Weak or missing

1. **No trained vision model.** The single biggest credibility hole. A judge holding up a
   random object is the known failure demo. The abstention seam exists, but the model that
   fills it does not.
2. **No ML of our own anywhere.** Health = rules, labels = keywords, LLM = Groq API,
   speech = Sarvam API. Reads as "FastAPI + someone else's API."
3. **The data flywheel is open-loop.** Beautiful labeled data is collected that trains
   nothing.
4. **Zero offline capability** — needs server + internet + two external APIs. Rural
   Karnataka is the target environment.
5. **No accuracy number exists for anything.**
6. **README is stale** — documents `/inspections/*` endpoints that no longer exist.
7. SQLite + no migrations; `evaluate_offline()` only runs when status is queried.

---

## 13. Agreed direction (SIH strategy)

### The killer feature: FORESIGHT

*A 96-hour pre-symptomatic disease early-warning engine with a self-labeling
verification loop.*

Every competing team builds **detection** — photograph a sick leaf, name the disease. But
by the time lesions are visible, red rot has already spread and the yield loss is locked
in. **Detection is a post-mortem.**

Fungal infection requires an environmental window — sustained humidity, temperature in
the pathogen's band, for a minimum number of consecutive hours (the *disease triangle*).
**The ESP32 already measures exactly those variables every 30 seconds.** So Gage can warn
*before symptoms exist*, then use the later photo to confirm or refute — which
**automatically labels the earlier prediction** and feeds the Dataset Builder. The
flywheel closes.

**The moat:** per-field, per-30-second canopy microclimate history. A competing team
using public weather APIs gets district-level daily averages. They cannot reproduce the
input data in a weekend.

### Build order

1. **Real vision classifier + OOD rejection** ← current phase, highest priority
2. Foresight engine (time-series store, rolling accumulators, disease-pressure model)
3. Flywheel closure (prediction↔outcome linker, auto-label, retrain)
4. Trust (evaluation harness, calibration, confidence-gated abstention)
5. Offline-first (on-device model, ESP32 store-and-forward, Postgres + Alembic)

### Explicitly NOT building

Blockchain · drones/satellite NDVI · farmer marketplace · multi-crop expansion ·
React/Flutter rewrite · more dashboard charts · generic PlantVillage demo.

### The demo moment

A judge holds up a random object. The system replies: **"This is not sugarcane foliage. I
will not diagnose it."** Then the Foresight replay shows it predicted red rot four days
before it was visible. Knowing when it doesn't know is the differentiator.

---

## 14. Vision training plan (next phase)

- **Classes:** `healthy, red_rot, rust, yellow_leaf, mosaic, leaf_spot, not_sugarcane`
- **Honest limit to state openly:** smut and grassy shoot are whole-plant/shoot symptoms,
  not leaf-patch symptoms — a leaf classifier structurally cannot detect them.
- **Data:** public sugarcane leaf datasets (Mendeley/Kaggle — **note PlantVillage contains
  no sugarcane**) + ~200 self-shot field photos + ~200 non-crop images for `not_sugarcane`.
- **Critical:** public sets contain many photos of the *same* leaf. **Split by
  plant/source, never randomly** — random splits leak near-duplicates and produce a "97%
  accuracy" that collapses under questioning. An honest 84% is worth more.
- **Model:** EfficientNet-B0 / MobileNetV3, ImageNet transfer, 224px, heavy augmentation
  to close the lab→field domain gap.
- **Calibration:** temperature scaling on a validation split.
- **Deployment:** ONNX, INT8-quantised. Server-side first, on-device later, no retraining.
- **Eval to report:** confusion matrix, per-class recall, ECE, OOD rejection rate, and the
  train/test split protocol.
- Environment: `torch 2.12.0+cpu` installed, no CUDA locally → train on Colab.

---

## 15. Working conventions

- **Phased delivery**: compile/run/verify before proceeding, commit only after passing,
  stop at each phase boundary.
- **Ponytail mode**: the laziest solution that actually works. YAGNI, stdlib over
  dependencies, shortest correct diff. Deliberate shortcuts are marked with a
  `ponytail:` comment naming the ceiling and the upgrade path.
- **Honesty over optimism**: no invented metrics. Anything unmeasured is labeled
  **TARGET METRIC**, with the experiment that would produce a real number.
- Never commit `.env`. Scan diffs for `sk_` / `gsk_` before pushing.
- Bump the `?v=NN` asset version on every frontend change.

---

## 16. Recent commit history

```
71a641a  Voice: never speak text in a language the device has no voice for
80da81b  Vision: structured verdict with an explicit abstention path
132df5d  Redesign the UI: icon system, restrained palette, calmer hierarchy
721c197  Sarvam STT: bump model to saarika:v2.5
a4dc935  Home: press-to-play voice, word-based soil moisture, freshness-based live status
bfb174d  Sarvam: use inputs[] TTS body, cap length, log real error body
6b72311  Fix formatting in README.md
4f7dc82  hardware guide: note HTTPS needed for phone mic/GPS
6d61a39  Add hardware connection guide (docs/hardware.md)
8017892  Fix Groq model id: openai/gpt-oss-120b (was gpt-oss-120b -> 404)
```

Repo: `https://github.com/MohammedZaid-AI/Gage` · branch `main`
