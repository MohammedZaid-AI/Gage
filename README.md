# 🌱 Gage
**AI-powered multilingual agricultural field assistant.** Gage guides farmers
during field inspections while automatically collecting structured agricultural
data for future AI models.

Low-cost monitoring nodes (an ESP32 with soil-moisture and temperature/humidity
sensors) report field conditions; farmers use the web app on their phone. This
backend ingests the readings, raises and resolves alerts, stores observations, and
answers questions in **English and Kannada**.

---

## Quick start

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # then set JWT_SECRET (required) and GROQ_API_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"   # a JWT_SECRET value

uvicorn backend.main:app --reload
```

Open **http://localhost:8000** for the dashboard.

### Local demo data

No demo account exists by default. For a local demo, set `SEED_DEMO=true` in `.env`
before starting the server: it creates farmer `9999999999` / password `demo1234`, a
farm, and node `demo-node-1` with API key `demo-node-key-123`. These credentials are
public, so never enable `SEED_DEMO` on a server other people can reach.

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
