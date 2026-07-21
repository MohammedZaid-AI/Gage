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
| Vision     | OpenCV pixel analysis (mock provider)   |
| LLM        | Templated bilingual answers (mock)      |
| Frontend   | Plain HTML/CSS/JS + WebSocket           |

No API keys needed — the mock providers do real work (OpenCV analyses each
image; the assistant grounds every answer in the latest observation).

---

## API

| Method | Path                  | Purpose                                  |
|--------|-----------------------|------------------------------------------|
| GET    | `/`                   | Dashboard                                |
| GET    | `/api/state`          | Snapshot for initial render              |
| WS     | `/ws`                 | Live updates (observation/inspection/robot) |
| POST   | `/inspections/start`  | Begin an inspection session              |
| POST   | `/inspections/stop`   | End the active session                   |
| GET    | `/inspections/current`| Active session (or null)                 |
| POST   | `/observations`       | Upload image + sensors (multipart)       |
| GET    | `/observations`       | Recent observations                      |
| POST   | `/chat`               | Ask the assistant (auto-detects language)|
| POST   | `/robot/{forward,backward,left,right,stop}` | Movement commands  |

Interactive docs at **http://localhost:8000/docs**.

### Upload an observation (what the phone posts)

```bash
curl -F "image=@leaf.jpg" -F "temperature=27.5" -F "humidity=61" \
     -F "soil_moisture=42" -F "gps_lat=12.97" -F "gps_long=77.59" \
     http://localhost:8000/observations
```

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
  models.py        Inspection, Observation, Conversation
  schemas.py       Pydantic I/O
  realtime.py      WebSocket broadcast hub
  state.py         in-memory robot telemetry
  ai/              provider abstraction (base + mock + service facade)
  routers/         inspection, observation, robot, chat
frontend/
  dashboard.html · css/style.css · js/dashboard.js
storage/
  images/          uploaded photos
  observations.db  SQLite
```

---

## Extending the AI

Business logic only touches `backend/ai`'s `describe_image` /
`answer_question`. To add Gemini, OpenAI, Ollama, Qwen2.5-VL or Gemma:

1. Implement `VisionProvider` / `LLMProvider` (`backend/ai/base.py`).
2. Route to it in `_select_vision` / `_select_llm` (`backend/ai/service.py`).
3. Set `VISION_PROVIDER` / `LLM_PROVIDER` + keys in `.env`.

No router or database changes needed.

## Wiring the ESP32

Robot commands land in `_dispatch` (`backend/routers/robot.py`). Drop your
serial / MQTT / HTTP call there — everything else already logs and broadcasts.
