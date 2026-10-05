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

Run the smoke test (starts nothing, checks the core logic):

```bash
python -m backend.selftest
```

---

## What runs where

| Layer      | Tech                                    |
|------------|-----------------------------------------|
| Backend    | FastAPI, SQLAlchemy 2, Pydantic v2      |
| Database   | SQLite (`storage/observations.db`)      |
| LLM        | Groq `openai/gpt-oss-120b` (default)    |
| Retrieval  | multilingual-e5 over `knowledge_base/`  |
| Voice      | Sarvam STT/TTS                          |
| Frontend   | Plain HTML/CSS/JS + WebSocket           |

The default LLM provider is **Groq** (`LLM_PROVIDER=groq` in `.env.example`; needs
`GROQ_API_KEY`). `LLM_PROVIDER=mock` runs fully offline with templated answers, and
`LLM_PROVIDER=sarvam_finetuned` runs the local fine-tuned Sarvam-1 adapter (GPU).

---

## API

| Method | Path                  | Purpose                                  |
|--------|-----------------------|------------------------------------------|
| GET    | `/`                   | Dashboard                                |
| GET    | `/api/state`          | Snapshot for initial render              |
| WS     | `/ws`                 | Live updates                             |
| POST   | `/chat`               | Ask the assistant (auto-detects language)|

Interactive docs at **http://localhost:8000/docs**.

### Ask in Kannada

`/chat` needs a login token and the id of one of your farms:

```bash
# 1. log in (the demo farmer is seeded on first start) and copy access_token
curl -X POST http://localhost:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"phone": "9999999999", "password": "demo1234"}'

# 2. ask, with the token and your farm id (GET /farms lists them)
curl -X POST http://localhost:8000/chat \
     -H "Authorization: Bearer <access_token>" \
     -H "Content-Type: application/json" \
     -d '{"farm_id": 1, "question": "ಈ ಗಿಡ ಹೇಗಿದೆ?"}'
```

---

## Project layout

```
backend/
  main.py          FastAPI app, static mounts, WebSocket, /api/state
  config.py        env-driven settings (.env)
  database.py      engine + session
  models.py        Observation, Conversation
  schemas.py       Pydantic I/O
  realtime.py      WebSocket broadcast hub
  ai/              provider abstraction (base + mock + service facade)
  routers/         observation, chat
frontend/
  dashboard.html · css/style.css · js/dashboard.js
storage/
  images/          uploaded photos
  observations.db  SQLite
```

---

## Extending the AI

Chat goes through `AIOrchestrator.answer` (`backend/ai/orchestrator.py`), which
assembles the Farm Context, retrieves knowledge, builds the structured prompt,
and calls the provider via `backend/ai/service.py`. To add Gemini, OpenAI,
Ollama or Gemma:

1. Implement `LLMProvider` (`backend/ai/base.py`).
2. Route to it in `_select_llm` (`backend/ai/service.py`).
3. Set `LLM_PROVIDER` + keys in `.env`.

No router or database changes needed.
