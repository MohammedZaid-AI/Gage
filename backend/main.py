"""Gage backend entrypoint. Run: uvicorn backend.main:app --reload"""
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db, init_db
from backend.models import Observation
from backend.realtime import broadcaster
from backend.routers import chat, inspection, observation, robot
from backend.routers.inspection import active_inspection
from backend.schemas import InspectionOut, ObservationOut
from backend.state import robot_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Gage", description="AI agricultural field assistant")

app.include_router(inspection.router)
app.include_router(observation.router)
app.include_router(robot.router)
app.include_router(chat.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/state")
def get_state(db: Session = Depends(get_db)) -> dict:
    """One-shot snapshot for initial dashboard render (WS handles live updates)."""
    insp = active_inspection(db)
    latest = db.execute(
        select(Observation).order_by(Observation.timestamp.desc()).limit(1)
    ).scalar_one_or_none()
    recent = list(
        db.execute(select(Observation).order_by(Observation.timestamp.desc()).limit(20)).scalars()
    )
    return {
        "robot": robot_state,
        "inspection": InspectionOut.model_validate(insp).model_dump(mode="json") if insp else None,
        "observation_count": db.query(Observation).count(),
        "latest_observation": ObservationOut.model_validate(latest).model_dump(mode="json") if latest else None,
        "history": [ObservationOut.model_validate(o).model_dump(mode="json") for o in recent],
    }


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep the socket open; inbound is ignored
    except WebSocketDisconnect:
        await broadcaster.disconnect(websocket)


# --- static: uploaded images + frontend ---
settings = get_settings()
_ROOT = Path(__file__).resolve().parent.parent
app.mount("/storage/images", StaticFiles(directory=settings.image_dir), name="images")
app.mount("/static", StaticFiles(directory=_ROOT / "frontend"), name="static")


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(_ROOT / "frontend" / "dashboard.html")
