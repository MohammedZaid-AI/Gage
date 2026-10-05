# 🌱 Gage
**AI-powered multilingual agricultural field assistant.** Gage guides farmers
during field inspections while automatically collecting structured agricultural
data for future AI models.

Low-cost monitoring nodes (an ESP32 with soil-moisture and temperature/humidity
sensors) report field conditions; farmers use the web app on their phone. This
backend ingests the readings, raises and resolves alerts, stores observations, and
answers questions in **English and Kannada**.

---

## Quick start (from a fresh clone)

Tested end to end on 5 October 2026 (clone of the local branch, new virtual environment,
fresh database, login: `test_runs/part6_fresh_install.txt`). Windows PowerShell;
on Linux/macOS use `source .venv/bin/activate` and `export` instead of `$env:`.

```powershell
git clone --branch hardening-pass https://github.com/MohammedZaid-AI/Gage.git
cd Gage
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt        # ~1.3 GB installed (CPU torch); use python -m pip
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste as JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste as NODE_KEY_SECRET
```

Edit `.env`: set `JWT_SECRET` (required, the app refuses to start without it),
`NODE_KEY_SECRET`, `GROQ_API_KEY` (the live answerer), and for voice
`SPEECH_PROVIDER=sarvam` with `SARVAM_API_KEY`. Then create the database and a
login (the script creates the tables on a new database):

```powershell
$env:GAGE_DEMO_PASSWORD = "choose-a-password"
python scripts/create_demo_farmer.py --phone 9876543210 --name "Ravi"
# prints the node API key ONCE: put it in the ESP32 firmware (NODE_KEY)
python -m uvicorn backend.main:app --port 8000
```

Open **http://localhost:8000** and log in with that phone number and password.
The first start downloads the embedding model (`intfloat/multilingual-e5-small`,
~470 MB) and builds the knowledge index, so it takes a minute or two.
For a GPU and the exact package versions, see [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).

### Local demo data

No demo account exists by default; use `scripts/create_demo_farmer.py` above.
Alternatively set `SEED_DEMO=true` in `.env` before starting the server: it
creates farmer `9999999999` / password `demo1234`, a farm, and node `demo-node-1`
with API key `demo-node-key-123`. These credentials are public, so never enable
`SEED_DEMO` on a server other people can reach.

### Node API keys

A node's API key is shown **once**, when the node is registered (or when you press
**New key** in Settings); only an HMAC of it is stored. Copy it into the device's
`NODE_KEY`. Set `NODE_KEY_SECRET` in `.env` so `JWT_SECRET` can be rotated without
invalidating device keys.

---

## What runs where

| Layer | What it is |
|---|---|
| Backend | FastAPI, SQLAlchemy 2, Pydantic v2 |
| Database | SQLite (`storage/observations.db`) |
| Answers | Groq `openai/gpt-oss-120b` (default, `LLM_PROVIDER=groq`) |
| Query rewrite + fact check | Groq `openai/gpt-oss-20b` (`GROQ_HELPER_MODEL`), under a per-minute token budget |
| Local checks | numbers, inputs, judgements and names checked against the sources, no network (`backend/ai/number_check.py`, `claim_check.py`) |
| Retrieval | multilingual-e5-small over `knowledge_base/` (25 documents) |
| Voice | Sarvam STT (saarika) and TTS (bulbul), Kannada and English |
| Sensor-pattern check | FlyBrain (flycns LIF simulation) on a synthetic test graph by default; see `GET /farm/{id}/anomaly` for the graph in use |
| Frontend | plain HTML/CSS/JS + WebSocket (`frontend/`) |

**Answer engine.** `LLM_PROVIDER` in `.env` sets the default (`groq`). Each chat
request can choose its engine: `POST /chat` with `"provider": "groq"` or
`"provider": "sarvam_finetuned"`, or the **Answer engine** dropdown in the Ask
panel; every answer bubble says which engine wrote it. The fine-tuned Sarvam-1
adapter (local GPU) is loaded once, on the first request that asks for it, never
at startup. If its model or GPU is missing, that request gets a clear HTTP 503;
it is never answered by Groq instead. Both engines get the same retrieval, the
same local number and name checks and the same caveat. (`mock` returns a fixed
text and is for offline tests only.) How the two compare:
[docs/FINAL_REPORT.md](docs/FINAL_REPORT.md). Gage does not analyse
photos: images uploaded by a node are stored with the observation, nothing more.

How an answer is made (`backend/ai/orchestrator.py`): build the farm context →
retrieve the top 4 knowledge chunks (the question as written; if that scores
below 0.87, also a Sarvam translation and a Groq rewrite) → structured prompt
(knowledge or farm question, number rules, four sections) → Groq answer →
local checks + Groq fact check → one caveat naming anything unsupported.

---

## API

Interactive docs at **http://localhost:8000/docs**. Farmer endpoints take
`Authorization: Bearer <token>` from `/auth/login`; node endpoints take
`X-Node-Key: <node key>`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login` · GET `/auth/me` | accounts |
| GET/POST | `/farms` · `/farms/{id}/nodes` · POST `/farms/{id}/nodes/{node}/rotate-key` | farms, nodes, node keys |
| POST | `/node/sensors`, `/node/heartbeat`, `/node/image` · GET `/node/status`, `/node/history` | device ingest (node key) |
| GET | `/farm/{id}/summary`, `/timeline`, `/health`, `/anomaly` | dashboard data |
| GET | `/alerts` · POST `/alerts/{id}/resolve` | alerts |
| POST | `/chat` | ask Gage (English, Kannada, Kanglish) |
| POST | `/voice/ask` (audio) · `/voice/speak` (text) | voice in and out |
| GET/POST | `/dataset`, `/dataset/stats`, `/dataset/export` | collected training data |
| GET | `/api/state` · WS `/ws` | dashboard snapshot and live updates |

### Ask in Kannada

```bash
# 1. log in and copy access_token
curl -X POST http://localhost:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"phone": "9876543210", "password": "<your password>"}'

# 2. ask, with the token and your farm id (GET /farms lists them)
curl -X POST http://localhost:8000/chat \
     -H "Authorization: Bearer <access_token>" \
     -H "Content-Type: application/json" \
     -d '{"farm_id": 1, "question": "ಪ್ರತಿ irrigation ಗೆ ಎಷ್ಟು cm water ಹಾಕ್ಬೇಕು?"}'
```

The response has the answer, `sources` (retrieved documents and scores),
`fact_check` (`checked`, `skipped` or `unavailable`) and `unsupported_claims`.

---

## Tests

```bash
python -m backend.selftest                 # offline logic checks (mock providers)
python scripts/check_security.py --base http://localhost:8000   # security checks, running server
python scripts/validate_pipeline.py        # against a running server
python scripts/acceptance.py --base http://localhost:8000 --phone ... --password ...
python scripts/eval_flybrain.py            # FlyBrain vs IsolationForest vs z-score (requirements-dev.txt)
```

Raw outputs of the October 2026 runs are in `test_runs/`; the summary is
[docs/FINAL_REPORT.md](docs/FINAL_REPORT.md).

---

## Project layout

```
backend/
  main.py            FastAPI app, static mounts, WebSocket, /api/state, startup tasks
  config.py          settings from .env
  models.py          SQLAlchemy tables (farmers, farms, nodes, readings, observations,
                     alerts, conversations, anomaly scores, ...)
  ai/                orchestrator, prompt builder, retrieval, Groq client + budget,
                     claim/number checks, FlyBrain, providers (groq, sarvam_finetuned, mock)
  services/          farm context, alerts, health score, observations, anomaly, node keys
  routers/           auth, farm, farm_intel, node, observation, chat, voice, alerts, dataset
  dataset/           training-data collection and export
knowledge_base/      the curated documents Gage answers from
frontend/            dashboard.html · css/style.css · js/dashboard.js
firmware/            ESP32 node sketch
scripts/             create_demo_farmer, acceptance, eval_flybrain, security and pipeline checks
docs/                ENVIRONMENT, KNOWN_LIMITATIONS, OPEN_ITEMS, FINAL_REPORT, audit
storage/             images/ (uploaded photos) and observations.db (SQLite, not in git)
```

---

## Extending the AI

To add another answering model (Gemini, OpenAI, Ollama ...):

1. Implement `LLMProvider` (`backend/ai/base.py`): `answer()` and optionally `summarize()`.
2. Route to it in `_select_llm` (`backend/ai/service.py`).
3. Set `LLM_PROVIDER` and its keys in `.env`.

No router or database changes needed.
