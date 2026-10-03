# Gage — Technical Audit (current state, not the plan)

**Date:** 2026-10-03 · **Commit audited:** `db0e38b` (branch `main`, clean tree)
**Method:** every tracked source file was read in full. The app was also imported and
booted, `python -m backend.selftest` and `scripts/validate_pipeline.py` were run against a
throwaway database, and a *copy* of the real dev DB (`storage/observations.db`) was
inspected. No calls were made to Groq or Sarvam.

---

## TL;DR — the five things that matter most

1. **The server does not start with the current `.env`.** `.env` sets
   `VISION_PROVIDER=tflite`. `backend/ai/service.py:21` then imports
   `backend.ai.providers.tflite_vision`, but **that file is not in the repo and never was in
   git history**. Only an orphaned compiled `__pycache__/tflite_vision.cpython-314.pyc` is
   left. The import sits *outside* the `try` meant to fall back to mock, so the result is
   `ModuleNotFoundError` at import time. Verified.
2. **The model files are also gone.** `./models/sugarcane/model_unquant.tflite` and
   `labels.txt` do not exist, and no `models/` folder exists. A search of `D:\` and
   `C:\Users` found no `model_unquant.tflite`. The DB shows the classifier *did* run
   locally: 3 observations carry real labels (`brown_spot` 0.95, `dried` 0.995) between
   2026-08-31 and 2026-09-23.
3. **None of these exist in this codebase:** a fine-tuned Sarvam LLM, a vector store or
   embedding RAG, YOLOv9, or FlyBrain. Not even as stubs. The LLM is Groq-hosted
   `openai/gpt-oss-120b`, Sarvam is used **only** for STT/TTS over its HTTP API, and "RAG"
   is keyword matching over 17 hard-coded paragraphs.
4. **The frontend fabricates sensor data.** Each "Scan crop" tap posts **random**
   temperature/humidity/soil values to `/node/sensors` (`frontend/js/dashboard.js:572-573`)
   before uploading the photo. Those fake readings flow into observations, alerts, health
   scores, LLM prompts and the training dataset.
5. **Alerts are never resolved.** No code anywhere sets `Alert.resolved = True`, and no
   endpoint exists to do it. Once an alert type fires for a node, it stays open forever:
   it keeps penalising the health score and is de-duplicated, so it never fires again. In
   the real DB, a `soil_low` alert from 2026-07-26 is still open.

With `VISION_PROVIDER=mock` the stack runs: self-test passes, and the pipeline validator
passes 25/25.

---

## 1. Project structure

```
Gage/
├── .env                      (gitignored) real local config incl. live Groq + Sarvam keys
├── .env.example              config template (placeholders)
├── .gitignore                ignores .env, pycache, storage DB/images/datasets, venvs
├── .vscode/c_cpp_properties.json   editor include paths (for the .ino)
├── README.md                 STALE — documents /inspections, /robot, POST /observations (all deleted)
├── requirements.txt          Python deps (see §6)
│
├── backend/                  ── BACKEND (FastAPI) ──
│   ├── main.py               app factory, router wiring, startup (create tables + seed), /api/state, /ws, static mounts
│   ├── config.py             pydantic-settings Settings (all env vars)
│   ├── database.py           engine/session, create_all + "self-heal" ALTER TABLE ADD COLUMN
│   ├── models.py             ORM: Farmer, Farm, Node, NodeHealth, NodeHeartbeat, SensorReading, Observation, Alert, Conversation
│   ├── schemas.py            Pydantic request/response models
│   ├── dependencies.py       get_current_farmer (JWT), owned_farm (ownership), get_node (X-Node-Key)
│   ├── realtime.py           in-process WebSocket broadcaster
│   ├── seed.py               idempotent demo farmer/farm/node
│   ├── selftest.py           offline smoke test (≈16 checks, own in-memory-style DB)
│   ├── core/security.py      bcrypt hashing, JWT issue/verify, node API key generation
│   ├── routers/              HTTP endpoints: auth, farm, farm_intel, node, observation, chat, voice, dataset
│   ├── services/             observation_service (merge + vision + summary), alerts, farm_context, health_score
│   ├── ai/                   ── AI / ML INTEGRATION ──
│   │   ├── base.py           provider ABCs (Vision/LLM/Speech), VisionResult, 11 disease class names
│   │   ├── service.py        provider selection + facade (analyze_image, complete, transcribe, synthesize)
│   │   ├── mock.py           offline providers (OpenCV colour stats, templated answers, silent WAV)
│   │   ├── orchestrator.py   chat pipeline: context → keyword RAG → prompt → LLM → save turn
│   │   ├── prompt_builder.py the only place farm data becomes prompt text
│   │   ├── knowledge.py      17 hard-coded sugarcane paragraphs + keyword retrieval
│   │   └── providers/
│   │       ├── groq_provider.py    real LLM (OpenAI SDK → api.groq.com)
│   │       ├── sarvam_provider.py  real STT/TTS (httpx → api.sarvam.ai)
│   │       └── tflite_vision.py    ✗ MISSING (only an orphaned .pyc remains)
│   └── dataset/              ── DATA (training-set builder) ──
│       ├── models.py         DatasetEntry, DatasetExport tables
│       ├── service.py        build entry per observation, link conversations
│       ├── quality.py        0–100 completeness score
│       ├── labels.py         rule/keyword auto-labels
│       ├── validators.py     NEW → VALIDATED at quality ≥ 50
│       ├── repository.py     filtered queries + stats
│       ├── exporter.py       JSONL / CSV / Parquet file export with SHA-256
│       └── schemas.py        API models
│
├── frontend/                 ── FRONTEND (plain HTML/CSS/JS SPA, served by FastAPI) ──
│   ├── dashboard.html        shell: login + 5-tab app
│   ├── css/style.css         design system (504 lines)
│   └── js/dashboard.js       router, views, API calls, voice, WebSocket (715 lines)
│
├── firmware/esp32_node.ino   ── HARDWARE ── ESP32 sketch: DHT22 + soil + LDR → POST /node/sensors, /node/heartbeat
├── scripts/
│   ├── reset_dev_db.py       backs up + recreates the dev SQLite DB
│   └── validate_pipeline.py  end-to-end HTTP harness against a running server
├── docs/                     PROJECT_CONTEXT.md (partly stale), demo.md, hardware.md, validation_report.md
└── storage/                  ── DATA (gitignored runtime) ──
    ├── observations.db       live dev SQLite DB (≈808 KB) + 2 .bak-* backups
    ├── images/               55 uploaded JPEGs
    └── datasets/             export output dir (currently empty)
```

**There is no `models/` directory, no training code, no notebooks, no dataset files, and
no mobile app project.**

---

## 2. Backend

### 2.1 Framework / runtime (as installed on this machine)

| Item | Version |
|---|---|
| Python | 3.14.2 (system install, no venv in repo) |
| FastAPI | 0.128.0 |
| SQLAlchemy | 2.0.45 |
| Pydantic | 2.12.5 (+ pydantic-settings) |
| Server | uvicorn |

The app uses the deprecated `@app.on_event("startup")` hook (`main.py:50`). There are no
middleware, CORS, rate limits or exception handlers.

### 2.2 Every endpoint (from the live OpenAPI schema, behaviour from the function bodies)

**Auth** (`routers/auth.py`)

| Method | Path | Auth | What it actually does | Status |
|---|---|---|---|---|
| POST | `/auth/register` | none | 409 if the phone exists; bcrypt-hashes the password; creates a Farmer (language defaults to `kn`); returns a JWT | Working |
| POST | `/auth/login` | none | Looks up by phone, verifies bcrypt, returns a JWT; 401 otherwise | Working |
| GET | `/auth/me` | JWT | Returns the current farmer | Working |

**Farms & nodes** (`routers/farm.py`)

| Method | Path | Auth | Behaviour | Status |
|---|---|---|---|---|
| POST | `/farms` | JWT | Creates a farm owned by the caller | Working |
| GET | `/farms` | JWT | Lists the caller's farms | Working |
| POST | `/farms/{farm_id}/nodes` | JWT + ownership | Registers a node with a caller-chosen id and a random `api_key` (returned in the response). 409 if the id exists | Working |
| GET | `/farms/{farm_id}/nodes` | JWT + ownership | Lists nodes **including their plaintext API keys** | Working |

There is **no update or delete** for farms, nodes or farmers, and no way to rotate a key.

**Farm intelligence** (`routers/farm_intel.py`)

| Method | Path | Behaviour | Status |
|---|---|---|---|
| GET | `/farm/{id}/summary` | Builds the FarmContext and rule-based health score; returns the latest observation's sensors, trends, open alerts and the latest observation's stored `ai_summary` (no fresh LLM call) | Working |
| GET | `/farm/{id}/timeline?limit=50` | Observations, newest first | Working |
| GET | `/farm/{id}/health` | Health score only | Working (frontend never calls it) |

**Device ingest** (`routers/node.py`, auth = `X-Node-Key` header)

| Method | Path | Behaviour | Status |
|---|---|---|---|
| POST | `/node/image` | Multipart image + optional GPS/timestamp. Merges into this node's latest observation if it lacks an image and is under 60 s old, otherwise creates a new one. Saves the file, runs **vision synchronously**, generates the **LLM summary synchronously** once both image and sensors are present, upserts a dataset entry, broadcasts over WS | Working with mock vision; **crashes the app at import if `tflite` is selected** (see §3.3) |
| POST | `/node/sensors` | JSON temp/humidity/soil/battery. Logs a SensorReading, merges into an observation (same rule), may generate the summary, evaluates alert thresholds, upserts the dataset entry, broadcasts | Working |
| POST | `/node/heartbeat` | Upserts NodeHealth, appends NodeHeartbeat, low-battery alert, broadcasts | Working |
| GET | `/node/status` | The node's health + its open alerts | Working (used only by the validator script) |
| GET | `/node/history?limit=50` | The node's observations + raw readings | Working (unused by the frontend) |

**Observations / chat / voice**

| Method | Path | Behaviour | Status |
|---|---|---|---|
| GET | `/observations/farms/{farm_id}` | Same data as `/farm/{id}/timeline` (duplicate) | Working, unused |
| POST | `/chat` | Ownership check → `AIOrchestrator.answer` (context → keyword RAG → prompt → LLM → save Conversation) | Working. Declared `async def` but makes blocking DB + Groq calls, so it **blocks the event loop** for the full LLM latency |
| POST | `/voice/ask` | Form `farm_id` + `audio` → STT → orchestrator → TTS → JSON with base64 audio. The STT-reported language is discarded (`_lang`); the answer language is re-detected from the transcript's script | Working on mock; Sarvam path untested here. Also `async` with blocking calls |
| POST | `/voice/speak` | Text → TTS → base64 audio | Working |

**Dataset** (`routers/dataset.py`, JWT)

| Method | Path | Behaviour | Status |
|---|---|---|---|
| GET | `/dataset` | Filtered entries for the caller's farms. Rewrites conversation links on **every read** | Working |
| GET | `/dataset/stats` | Counts, quality, daily rate, export history | Working, but **leaks other tenants' export history** (verified, §7.4) |
| POST | `/dataset/export` | Writes a file to `./storage/datasets/` on the server and marks entries EXPORTED. Returns the server-side path | Working, but **there is no download endpoint**, so the file is unreachable over the API |
| GET | `/dataset/{entry_id}` | One entry (ownership-checked) | Working |

**Unauthenticated app-level routes** (`main.py`)

| Method | Path | Behaviour |
|---|---|---|
| GET | `/` | Serves `frontend/dashboard.html` |
| GET | `/api/state` | **No auth.** Returns the *first farm in the DB*: observations, nodes, alerts. It is also the **only** trigger for offline-node detection. The current frontend never calls it |
| WS | `/ws` | **No auth.** Every connected client gets every farm's observation/alert/node events |
| static | `/static/*` | Frontend assets |
| static | `/storage/images/*` | **No auth.** Every uploaded field photo, by filename |

**Missing entirely:** alert acknowledge/resolve, conversation history, farm/node
update/delete, export download, password reset, refresh tokens, any admin role.

### 2.3 Auth implementation (`core/security.py`, `dependencies.py`)

- **Passwords:** `bcrypt.hashpw` with `gensalt()` (default cost 12). The input is
  explicitly truncated to 72 bytes. Minimum length is **4 characters**
  (`schemas.RegisterRequest`).
- **JWT:** PyJWT, HS256, payload `{sub: farmer_id, exp: now + 7 days}`. There is no `iat`,
  `jti`, issuer or audience, no refresh token and no revocation. Logout is client-side only.
- **Secret:** `JWT_SECRET` from env. **The local `.env` value equals the public default
  `dev-insecure-change-me`**, so anyone who reads this repo can mint a token for any
  farmer id.
- **Farmer scoping:** `owned_farm()` returns 404 if the farm is missing and 403 if it isn't
  the caller's. It is applied on every farm, node-list, summary, timeline, health,
  observation, chat and voice route. Dataset routes filter by the caller's farm ids.
  Verified: farmer B calling `/chat` with farmer A's farm gets 403.
- **Node auth:** an opaque `X-Node-Key` (`secrets.token_urlsafe(24)`) **stored in
  plaintext** and looked up directly. The demo node key `demo-node-key-123` is hard-coded
  in `seed.py`, the firmware, and the validator script.
- **No rate limiting** on login or register.

### 2.4 Data models (actual columns)

**Domain tables (`backend/models.py`)**

| Table | Columns |
|---|---|
| `farmers` | id PK, phone (unique, idx), password_hash, name?, language (`kn` default), created_at |
| `farms` | id PK, farmer_id → farmers, name, crop_type (`sugarcane`), village?, area_acres?, created_at |
| `nodes` | id (string PK, device id), farm_id → farms, name?, api_key (unique, plaintext), location?, created_at |
| `node_health` | node_id PK → nodes, status (`online`/`offline`), last_seen?, battery?, wifi_strength?, firmware_version?, gps_available?, camera_available?, storage_available?, updated_at |
| `node_heartbeats` | id, node_id, source (`esp32`/`phone`), battery?, wifi_strength?, firmware_version?, gps/camera/storage_available?, timestamp |
| `sensor_readings` | id, node_id, farm_id, temperature?, humidity?, soil_moisture?, battery?, timestamp, observation_id? → observations |
| `observations` | id (uuid hex), farm_id, node_id, timestamp, gps_lat?, gps_long?, image_path?, temperature?, humidity?, soil_moisture?, vision_summary?, vision_label?, vision_confidence?, ai_summary? |
| `alerts` | id, farm_id, node_id?, type, severity, message, value?, resolved (bool, **never set true**), created_at |
| `conversations` | id, farm_id, farmer_id, question, answer, language, timestamp |

**Dataset tables (`backend/dataset/models.py`)**

| Table | Columns |
|---|---|
| `dataset_entries` | id, observation_id (unique) → observations, farm_id, node_id, crop_type, timestamp, gps_lat/long, temperature, humidity, soil_moisture, vision_summary, ai_summary, image_path, active_alerts (JSON), labels (JSON), conversation_reference → conversations, weather_reference (**always NULL — placeholder**), quality_score, quality_reason, status (NEW/VALIDATED/EXPORTED/ARCHIVED), created_at, updated_at |
| `dataset_exports` | id, dataset_version, fmt, record_count, filters_used (JSON), checksum, path, created_at. **No farmer/farm column**, which is the cause of the leak |

Notes:
- `dataset_entries` does **not** store `vision_label` or `vision_confidence`. The
  classifier verdict survives only as one string inside `labels`.
- `ObservationOut` (the API schema) also **omits `vision_label` and `vision_confidence`**,
  so no client can see the structured verdict.
- `ARCHIVED` is defined but nothing ever sets it.

---

## 3. AI / ML integration

### 3.1 Fine-tuned Sarvam model — **does not exist in this codebase**

There is no fine-tuned model, no Sarvam LLM call, and no model weights, adapter, LoRA,
`transformers` or `torch` import. `git grep` for `fine-tun|lora|peft|transformers|torch|sarvam-m`
finds nothing in code. The only mentions are a docstring ("raw material for future
fine-tuning") and the plan in `docs/PROJECT_CONTEXT.md`.

**What actually answers questions:**
- `LLM_PROVIDER=groq` (current `.env`) → `GroqLLMProvider`
  (`ai/providers/groq_provider.py`). It uses the OpenAI SDK against
  `https://api.groq.com/openai/v1`, model `openai/gpt-oss-120b`, with two system messages
  (persona + the full built prompt) and the user question. There is no temperature, no
  max_tokens and no timeout override. Any exception returns a bilingual "temporarily
  unavailable" string, so failures are silent to the caller (HTTP 200).
- `LLM_PROVIDER=mock` → `MockLLMProvider`. It returns a **fixed template** filled with
  lines copied from the prompt. The "Analysis" is always "the plant appears broadly
  stable" and the confidence is always "Medium". In the real DB, **25 of 65 saved
  conversations are this offline template.**

**What Sarvam actually does:** STT and TTS only (§3.5).

### 3.2 RAG — **keyword matching, no vector store**

- Corpus: 17 `KnowledgeDoc` paragraphs hard-coded in `ai/knowledge.py` (6 general topics +
  11 disease/healthy docs, roughly 2–5 sentences each).
- Retrieval: lowercase `[a-z]{3,}` tokens from the question + last 5 conversation turns +
  the latest `vision_label` → score by keyword containment / shared 4-char prefix + title
  bonus → top 3. There are no embeddings, no vector DB and no persistence.
- **It is wired in:** `AIOrchestrator.answer` calls `knowledge.retrieve(...)` on every
  `/chat` and `/voice/ask`, and the result goes in the prompt's `# AGRICULTURAL KNOWLEDGE`
  section.
- **Limitation:** the tokeniser only matches ASCII, so a question written in Kannada script
  retrieves **nothing from the question itself**. It can only hit through prior English
  turns or the vision label.
- `ai_summary` generation at ingest (`summarize_observation`) **does not use RAG or the
  FarmContext**. It sends a short 5-line context to the same LLM.

### 3.3 Vision — MobileNet (via Teachable Machine) **source and weights missing**; YOLOv9 **absent**

**Configured path:**
- `config.py` / `.env.example`: `VISION_PROVIDER=tflite`,
  `VISION_MODEL_PATH=./models/sugarcane/model_unquant.tflite`,
  `VISION_LABELS_PATH=./models/sugarcane/labels.txt`, threshold 0.70, margin 0.15, min
  64 px, min Laplacian detail 60. The config comment calls it a "Teachable Machine export:
  a float32 224x224x3 MobileNet".
- `requirements.txt` includes `ai-edge-litert` (TFLite runtime). It is installed.
- `ai/base.py` hard-codes 11 classes: healthy, banded_chlorosis, brown_spot, brown_rust,
  dried, grassy_shoot, pokkah_boeng, sett_rot, smut, viral_disease, yellow_leaf.

**Reality:**
- `backend/ai/providers/tflite_vision.py` **is not in the working tree or in any commit**.
  Only `backend/ai/providers/__pycache__/tflite_vision.cpython-314.pyc` (16 KB, built
  2026-08-31) remains. Python will not import a `__pycache__` .pyc without its source.
- Its string constants show a real implementation existed: `ai_edge_litert.interpreter.Interpreter`
  loaded once behind a `threading.Lock`; centre-crop → resize → RGB → normalise; softmax;
  abstain below threshold or when top-1 minus top-2 is under the margin; reject
  blank/blurry frames (Laplacian variance); messages like "The image most closely matches
  X at N% confidence…".
- **`service.py:21` imports the module outside the `try/except`**, so the intended
  fall-back-to-mock never happens. Importing `backend.main` with the current `.env` raises
  `ModuleNotFoundError`. **The server cannot boot.**
- Even with the source restored, the weights are absent, so the `try` would catch
  `FileNotFoundError` and fall back to mock.
- **Model accuracy is unknown**: no evaluation code, metrics or split protocol exist in the
  repo.

**What runs when `VISION_PROVIDER=mock`:** `MockVisionProvider` computes HSV green/yellow
fractions and brightness with OpenCV and returns prose ("Healthy green foliage dominates
the frame…"), always with `abstained=True` and no label. It cannot identify a crop.

**How vision is invoked:** only from `observation_service.ingest_image`, synchronously
inside `POST /node/image`. There is no standalone script. **YOLOv9 / any detector: no
code, config, dependency or file anywhere.** MobileNetV2 is never named explicitly; only
"MobileNet" in a config comment. `docs/PROJECT_CONTEXT.md §14` plans EfficientNet-B0 /
MobileNetV3 via ONNX, which also does not exist.

### 3.4 FlyBrain — **nothing**

No match for `flybrain`, "fly brain" or anything similar in code, docs, config or git
history.

The closest planned concept is "Foresight" (pre-symptomatic disease warning from
microclimate history) in `docs/PROJECT_CONTEXT.md §13`. It is **plan only**: no
time-series store, no accumulators, no disease-pressure model.

### 3.5 Voice / STT / TTS — **implemented, Sarvam path unverified**

- `ai/base.py::SpeechProvider` (transcribe / synthesize).
- `MockSpeechProvider`: "STT" decodes the uploaded bytes **as UTF-8 text** (so real audio
  becomes "How is my field?"), and TTS returns a silent WAV.
- `SarvamSpeechProvider` (`.env` currently `SPEECH_PROVIDER=sarvam`):
  - STT: `POST https://api.sarvam.ai/speech-to-text`, model `saarika:v2.5`, `language_code`
    is always `unknown` (the router never passes a language). The file is sent as
    `audio.webm` / `audio/webm`. The code comment admits Sarvam may expect wav/mp3.
    **Untested here.**
  - TTS: `POST /text-to-speech` with `inputs:[text[:480]]`, `bulbul:v2`, speaker
    `anushka`. Answers longer than 480 characters are **silently truncated**, and Crop
    Doctor answers usually are.
  - The docstring says endpoint and field names must be confirmed against current Sarvam
    docs.
- Frontend: MediaRecorder → `/voice/ask`; a Play button plays returned audio, otherwise
  calls `/voice/speak`, otherwise uses browser `speechSynthesis` only if a matching-language
  voice exists.

---

## 4. Data

### 4.1 Training datasets

**No training dataset is referenced or used anywhere.** There are no Mendeley/Kaggle
paths, no dataset loaders and no training or eval scripts. The 11 class names in
`ai/base.py` are the only trace of whatever trained the missing model.

The **Dataset Builder** (`backend/dataset/`) produces data; it doesn't consume it. One
`DatasetEntry` is upserted per observation, with rule-based quality and labels, and can be
exported to JSONL/CSV/Parquet. Nothing reads those exports.

Label quality problems found:
- `labels.py::_CLASS_LABELS` maps `red_rot`, `rust`, `mosaic` and `leaf_spot`, which are
  **not classes of the current model**. It's harmless (falls through to identity) but
  stale.
- With mock vision, keyword fallback produces contradictory label sets. In the validator
  run, one entry was labelled `['dry_soil', 'healthy', 'high_humidity', 'water_stress']`.
- Because of the fake sensors in the frontend (§7.1), any entry created via "Scan crop"
  has **fabricated sensor values and labels derived from them**.

### 4.2 Database

- **Engine:** SQLite at `storage/observations.db` (`DATABASE_URL`). The code branches only
  on the `sqlite` prefix for `check_same_thread`. Postgres is untested.
- **Schema management:** `Base.metadata.create_all` plus `_sync_missing_columns()`, which
  issues `ALTER TABLE … ADD COLUMN` for missing columns. **No Alembic, no migrations.**
- **Current real DB contents** (read from a copy):

| Table | Rows |
|---|---|
| farmers | 1 (demo `9999999999`) |
| farms | 1 · nodes 1 (`demo-node-1`) |
| observations | 560 (2026-07-26 → 2026-09-23); 23 with image, 549 with sensors, **3 with a classifier label**, 12 with `ai_summary` |
| sensor_readings | 549 · node_heartbeats 5 |
| alerts | 2, both open (`soil_low` since 2026-07-26, `humidity_high` since 2026-08-31) |
| conversations | 65 (25 are mock-template answers) |
| dataset_entries | 560 (546 NEW, 14 VALIDATED) · dataset_exports 0 |
| node_health | `demo-node-1` = **"online"**, last_seen 2026-08-31 (stale, never re-evaluated) |

The schema matches the current models, including `vision_label` and `vision_confidence`.

### 4.3 Seed / sample data

- `backend/seed.py` runs on every startup when `SEED_DEMO=true` (the default and the
  current `.env`). It creates farmer `9999999999` / password `demo1234`, farm "Demo Farm"
  (Mandya, 2.5 acres), and node `demo-node-1` with key `demo-node-key-123`.
- The login form is **pre-filled with these credentials** (`dashboard.html:22,26`).
- 55 JPEGs in `storage/images/` (gitignored), from real uploads.
- `validate_pipeline.py` and `selftest.py` generate synthetic solid-colour images.

---

## 5. Frontend / mobile

- **No native mobile app exists.** The phone uses the same web SPA in its browser
  (`docs/hardware.md` step 5 says so).
- **Stack:** one HTML file + vanilla JS (715 lines) + CSS. No framework, no build, served
  by FastAPI at `/`.
- **Screens:** Login/Register → Home, Timeline → Detail, Ask, Reports, Settings.

| Screen | API calls | Notes |
|---|---|---|
| Login/Register | `POST /auth/login`, `POST /auth/register` | Register sends only phone + password, so every new farmer gets name = null and language = `kn` |
| Boot | `GET /auth/me`, `GET /farms`, `GET /farms/{id}/nodes` | Always picks the first farm |
| Home | `GET /farm/{id}/summary`, `GET /farms/{id}/nodes` | Health gauge, sensors, alerts, stored `ai_summary` |
| Scan crop | `POST /node/sensors` (**random values**), then `POST /node/image` | Uses the node's API key from the browser |
| Timeline | `GET /farm/{id}/timeline?limit=50` | Per-card health is a **client-side re-implementation** of the score |
| Detail | none | Recommendations, "Confidence" and "Why Gage said this" are **client-side if/else rules**, not AI. Labelled as Gage reasoning in the UI |
| Ask | `POST /chat`, `POST /voice/ask`, `POST /voice/speak` | Parses Observation/Analysis/Confidence/Recommendations by regex |
| Reports | `GET /farm/{id}/timeline?limit=300`, `GET /dataset/stats` | Daily/weekly/monthly averages computed in the browser |
| Settings | `GET/POST /farms`, `GET/POST /farms/{id}/nodes` | Shows node API keys in plaintext. Language preference is stored in localStorage and **never sent to the backend** |
| Live | `WS /ws` | Re-renders Home on any event from **any farm** |

The frontend never calls `/api/state`, `/farm/{id}/health`, `/observations/*`,
`/node/status`, `/node/history`, `/dataset` (list), `/dataset/{id}` or `/dataset/export`.

---

## 6. Config & dependencies

### 6.1 `requirements.txt` (unpinned lower bounds)

```
fastapi>=0.115            uvicorn[standard]>=0.34     sqlalchemy>=2.0.36
pydantic>=2.10            pydantic-settings>=2.7      python-multipart>=0.0.20
opencv-python-headless>=4.10                          ai-edge-litert>=1.2
python-dotenv>=1.0        openai>=1.50                bcrypt>=4.1
PyJWT>=2.9
```

- `httpx` (used directly by the Sarvam provider and the validator) and `numpy` are only
  present **transitively** (via openai / opencv).
- `pyarrow` (Parquet export) is optional and not listed.
- `python-dotenv` is listed but unused; pydantic-settings reads `.env` itself.
- There is no lock file, no `package.json`, and no dev/test requirements file.

### 6.2 Environment variables (all read in `backend/config.py::Settings`)

`DATABASE_URL`, `IMAGE_DIR`, `VISION_PROVIDER`, `LLM_PROVIDER`, `VISION_MODEL_PATH`,
`VISION_LABELS_PATH`, `VISION_CONFIDENCE_THRESHOLD`, `VISION_MARGIN_MIN`,
`VISION_MIN_IMAGE_PX`, `VISION_MIN_DETAIL`, `GEMINI_API_KEY` (unused), `OPENAI_API_KEY`
(unused), `GROQ_API_KEY`, `GROQ_MODEL`, `SPEECH_PROVIDER`, `SARVAM_API_KEY`,
`SARVAM_STT_MODEL`, `SARVAM_TTS_MODEL`, `SARVAM_SPEAKER`, `JWT_SECRET`, `JWT_ALGORITHM`,
`JWT_EXPIRE_MINUTES`, `SEED_DEMO`, `MERGE_WINDOW_SECONDS`, `OFFLINE_SECONDS`,
`HUMIDITY_MAX`, `SOIL_MOISTURE_MIN`, `TEMPERATURE_MAX`, `LOW_BATTERY_PERCENT`.

Current `.env` sets: `VISION_PROVIDER=tflite` (broken), `LLM_PROVIDER=groq`,
`SPEECH_PROVIDER=sarvam`, Groq and Sarvam keys present, `JWT_SECRET` = public default.
`.env` does **not** set the `VISION_MODEL_PATH` group, so code defaults apply.

### 6.3 Hard-coded values that should probably be config (listed, not fixed)

| Where | Value |
|---|---|
| `firmware/esp32_node.ino:13-14` | **Real-looking Wi-Fi SSID and password committed to git** (rotate the Wi-Fi password) |
| `firmware/esp32_node.ino:15-16` | Backend URL `http://192.168.1.100:8000`, node key `demo-node-key-123` |
| `firmware/esp32_node.ino:36` | `HUM_MAX = 90.0` while the backend uses **85.0**; the comment claims they mirror each other |
| `firmware/esp32_node.ino:114,127` | Battery always reported as `100`; LDR light % measured but never sent |
| `backend/seed.py:15-18` | Demo phone/password/node id/node key |
| `frontend/dashboard.html:22,26` | Demo credentials pre-filled in the login form |
| `frontend/js/dashboard.js:131` | Thresholds `{soilMin:20, humMax:85, tempMax:40}` duplicated client-side |
| `frontend/js/dashboard.js:361` | "Very wet" at soil > 60 (client-only rule) |
| `frontend/js/dashboard.js:572-573` | Fake sensor generator (24–30 °C, 55–75 %, 30–55 % soil, battery 95) |
| `backend/dataset/exporter.py:20` | `./storage/datasets` (ignores config, relative to CWD) |
| `backend/dataset/validators.py:7` | `MIN_QUALITY = 50` |
| `backend/services/farm_context.py:24-25` | Last 10 observations / last 5 conversation turns |
| `backend/services/health_score.py` | All deductions (20/15/15/20×conf/15/5-per-alert cap 25) and status bands |
| `backend/dataset/quality.py` | All quality weights, 7-day recency |
| `backend/ai/providers/groq_provider.py:40` | Groq base URL |
| `backend/ai/providers/sarvam_provider.py:20-22` | Sarvam base URL, 30 s timeout, 480-char TTS cap, `audio/webm` content type |
| `backend/ai/knowledge.py` | The entire knowledge base |
| `backend/ai/prompt_builder.py:117-119` | Claims "11 classes, trained on leaf/cane photographs" about a model that isn't present |
| `backend/main.py:124` | Image static mount assumes `image_path` is a path relative to the project root. If `IMAGE_DIR` is set to an absolute path, every image URL 404s (observed in testing) |

---

## 7. Integration gaps

### 7.1 Disconnected or broken links

1. **Vision provider → app boot.** `.env` selects `tflite`; the module source is missing
   and the import is outside the `try`, so the **app fails to import**.
   (`backend/ai/service.py:20-21`)
2. **Vision provider → model weights.** `models/sugarcane/*` does not exist anywhere.
3. **Classifier verdict → API/clients.** `vision_label` and `vision_confidence` are stored
   but not in `ObservationOut`, `FarmSummaryOut` or `DatasetEntryOut`. The frontend
   therefore uses keyword heuristics on prose instead of the verdict.
4. **Frontend "Scan crop" → real sensors.** It sends random sensor values every time
   (`dashboard.js:572-573`). `docs/hardware.md` acknowledges this as a temporary demo hack.
5. **Alerts → resolution.** There is no code path or endpoint to resolve an alert.
   Recovered conditions stay "active" forever.
6. **Offline detection → anything the app uses.** `alerts.evaluate_offline` runs only
   inside unauthenticated `GET /api/state`, which the SPA never calls. Node status never
   flips to offline in practice.
7. **Dataset exports → retrieval.** Files are written server-side with no download
   endpoint.
8. **Dataset → training.** Nothing consumes exports; there is no training or fine-tuning
   pipeline.
9. **RAG → Kannada.** ASCII-only tokenisation means Kannada-script questions don't drive
   retrieval.
10. **Ingest-time AI summary → orchestrator.** `summarize_observation` bypasses the
    FarmContext, RAG and the Crop Doctor prompt. It sends a 5-line context with a generic
    question.
11. **Health score vs prompt sensor source.** `health_score.compute` reads sensors from the
    latest *observation*, while `prompt_builder` reads the latest *SensorReading*. With an
    image-only latest observation, the score ignores fresh sensor data the LLM is shown.
12. **Detail screen → AI.** Its "Recommendations / Confidence / Why Gage said this" come
    from browser if/else rules, not the backend AI.
13. **Farmer language preference → backend.** The Settings toggle is localStorage only.
    The backend uses `Farmer.language` (fixed at registration; always `kn` from the UI)
    for summaries, and script detection for chat.
14. **STT language → answer.** `voice_ask` discards the language Sarvam reports.
15. **Sarvam STT → audio format.** The browser records webm/opus and it's sent as-is.
    Compatibility is unverified (flagged in the code itself).
16. **TTS → full answer.** Text is truncated at 480 chars server-side (the frontend sends
    up to 900).
17. **Weather → anything.** `DatasetEntry.weather_reference` is always NULL; no weather
    integration exists.
18. **Groq failures → caller.** Errors become an HTTP 200 apology string that is **saved
    as a Conversation** and linked into the dataset.
19. **Docs → code.** `README.md` documents deleted endpoints (`/inspections/*`, `/robot/*`,
    `POST /observations`) and says the defaults are "mock, no keys", while `.env.example`
    now defaults to `tflite` + `groq`. `PROJECT_CONTEXT.md §7` says `_select_vision()`
    "always returns MockVisionProvider" and lists a different 6-class set.

### 7.2 Concurrency

`/chat`, `/voice/ask`, `/node/image` and `/node/sensors` are `async def` but call
synchronous SQLAlchemy, OpenCV, Groq (OpenAI SDK) and httpx. One slow LLM or STT call
**stalls every other request**, including device ingest. The WebSocket broadcaster is
in-process, so it won't work across multiple workers.

### 7.3 Security / tenancy

- `GET /api/state`, `WS /ws` and `/storage/images/*` are **unauthenticated**.
  `/api/state` exposes farm 1's observations, nodes and alerts; `/ws` streams every
  tenant's events to anyone.
- `JWT_SECRET` in `.env` is the public default.
- Node API keys are stored in plaintext and shown in the UI and API responses.
- Minimum password length is 4; there is no login rate limit.
- Wi-Fi credentials are committed in `firmware/esp32_node.ino`.

### 7.4 Verified cross-tenant leak

`DatasetExport` has no owner column, and `DatasetRepository.stats` lists the latest 10
exports globally. **Verified:** farmer B (after creating any farm) sees farmer A's export
version, record count and checksum prefix in `GET /dataset/stats`.

### 7.5 TODO / FIXME comments

**There are zero `TODO`, `FIXME`, `HACK` or `XXX` comments in the repository.** The
project marks deliberate shortcuts with `ponytail:` instead. All of them, quoted:

| File:line | Comment |
|---|---|
| `backend/ai/knowledge.py:3` | "ponytail: a curated in-code KB with keyword-overlap retrieval (light stemming via a shared prefix so "irrigate" matches "irrigation")… Promote to a `knowledge_base` table + embeddings only when the corpus grows past keyword matching or farmers need to edit it." |
| `backend/config.py:50` | "ponytail: remove once real farmer onboarding exists." |
| `backend/config.py:60` | "ponytail: global constants for V1; make them per-crop / per-farm rows when agronomy demands it." |
| `backend/core/security.py:12` | "ponytail: stored in plaintext (needs lookup-by-key); hash it with a separate key id if at-rest protection becomes a requirement." |
| `backend/database.py:41` | "ponytail: a stopgap until Alembic; add real migrations before there is production data to preserve." |
| `backend/main.py:64` | "ponytail: single-farm demo view + offline check on read. Phase 4 makes the dashboard authenticated and per-farm; real clients use the farmer-scoped APIs." *(Phase 4 shipped; this route was never changed)* |
| `backend/routers/farm_intel.py:57` | "ponytail: reuse the observation's summary generated at merge — no fresh LLM call on a dashboard poll." |
| `backend/seed.py:3` | "ponytail: demo-only. Delete once real farmer onboarding exists (Phase 4+)." |
| `backend/services/alerts.py:94` | "ponytail: lazy (runs when status is queried). Move to a scheduled task when you need offline alerts without a dashboard viewer." |

Comments that work as TODOs:
- `backend/ai/providers/sarvam_provider.py:6-8`: "Confirm against the current Sarvam docs
  for your account before production".
- `backend/ai/providers/sarvam_provider.py:55-56`: "Browsers record webm/opus; Sarvam
  expects wav/mp3… if STT rejects the format the error body will say so."
- `backend/ai/base.py:22-26`: `not_sugarcane` "is NOT a class of the current model… the
  seam for a model retrained with a reject class".
- `backend/dataset/models.py:55`: `weather_reference … # future`.

---

## 8. How to run it right now

### 8.1 As-is (`python -m uvicorn backend.main:app`, current `.env`)

**It fails immediately** at import:

```
File "backend\ai\service.py", line 21, in _select_vision
    from backend.ai.providers.tflite_vision import TFLiteVisionProvider  # lazy
ModuleNotFoundError: No module named 'backend.ai.providers.tflite_vision'
```

### 8.2 Minimum change to boot

Set `VISION_PROVIDER=mock` in `.env` (or as an env var). Then:

**What works (verified with mock providers on a fresh DB):**
- Startup creates tables and seeds the demo farmer/farm/node.
- Login, register, `/auth/me`, farm and node create/list, ownership checks (403 across
  tenants).
- ESP32 contract: heartbeat, sensors, image → merged observation → alerts → dataset entry
  → WS broadcast.
- Farm summary, timeline and health score; dataset list, stats and export.
- `python -m backend.selftest` passes; `scripts/validate_pipeline.py` **passes 25/25**.
- With the current `.env` keys, `/chat` would hit **Groq GPT-OSS-120B** for real
  (not exercised in this audit) and voice would hit **Sarvam** for real (not exercised;
  STT webm compatibility unknown).

**What returns empty, fake or degraded data:**
- **Vision:** every image gets colour-statistics prose and no diagnosis. Disease-specific
  RAG docs are never pulled in by a verdict, and the model can't tell sugarcane from
  anything else.
- **"Scan crop"** writes random sensor values along with the photo.
- **Alerts** accumulate and never clear; the health score stays penalised.
- **Node online/offline** never updates (no `/api/state` caller).
- **Detail page** "AI" reasoning is browser rules.
- **Exports** can't be downloaded.
- **`weather_reference`** is always null; **`ARCHIVED`** is never used.
- With `LLM_PROVIDER=mock`, every chat answer is the same template with "Confidence:
  Medium".
- With `SPEECH_PROVIDER=mock`, real recorded audio becomes "How is my field?" and TTS is
  silence.
- On the phone over plain `http://<LAN-IP>`, browsers block mic and GPS (documented), so
  voice and GPS only work on `localhost` or over HTTPS.

### 8.3 To restore the real classifier

The code expects:
1. `backend/ai/providers/tflite_vision.py` defining `TFLiteVisionProvider()` (no args),
   implementing `analyze(bytes) -> VisionResult`. The behaviour is recoverable from the
   orphaned `.pyc` constants, and the file may still exist in another checkout or backup.
2. `models/sugarcane/model_unquant.tflite` + `labels.txt` (Teachable Machine format,
   224×224×3 float32, 11 classes matching `ai/base.py::DISEASE_CLASSES`).
3. Ideally, move the import inside the `try` in `service.py` so a missing provider degrades
   to mock instead of killing the app.
