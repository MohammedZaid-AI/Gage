# 🌱 Gage
**AI-powered multilingual agricultural field assistant.** Gage guides farmers
during field inspections while automatically collecting structured agricultural
data for future AI models.

An Android phone mounted on an ESP32 robot acts as camera, GPS, mic, speaker and
network. This backend ingests that data, describes crops with AI, stores
observations, and answers questions in **English and Kannada**.

---

## Quick start

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # defaults work out of the box (mock AI, no keys)

uvicorn backend.main:app --reload
```

Open **http://localhost:8000** for the dashboard.

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
| LLM        | Templated bilingual answers (mock)      |
| Frontend   | Plain HTML/CSS/JS + WebSocket           |

No API keys needed — the mock providers keep the app working offline (the
assistant grounds every answer in the latest observation).

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

```bash
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"question": "ಈ ಗಿಡ ಹೇಗಿದೆ?"}'
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
