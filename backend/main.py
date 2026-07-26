"""Gage backend entrypoint. Run: uvicorn backend.main:app --reload"""
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal, get_db, init_db
from backend.models import Alert, Farm, Node, NodeHealth, Observation
from backend.realtime import broadcaster
from backend.routers import (
    auth,
    chat,
    farm,
    farm_intel,
    node as node_router,
    observation,
    voice,
)
from backend.schemas import AlertOut, NodeHealthOut, ObservationOut
from backend.seed import seed_demo
from backend.services import alerts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Gage", description="AI agricultural field assistant")

app.include_router(auth.router)
app.include_router(farm.router)
app.include_router(farm_intel.router)
app.include_router(node_router.router)
app.include_router(observation.router)
app.include_router(chat.router)
app.include_router(voice.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    if get_settings().seed_demo:
        with SessionLocal() as db:
            seed_demo(db)


@app.get("/api/state")
def get_state(db: Session = Depends(get_db)) -> dict:
    """Snapshot of the first farm for the built-in dashboard (WS handles live updates).

    Also runs lazy offline detection: querying state refreshes node online/offline
    status and raises offline alerts.
    ponytail: single-farm demo view + offline check on read. Phase 4 makes the
    dashboard authenticated and per-farm; real clients use the farmer-scoped APIs.
    """
    if alerts.evaluate_offline(db):
        db.commit()

    farm_row = db.execute(select(Farm).order_by(Farm.id).limit(1)).scalar_one_or_none()
    if farm_row is None:
        return {"farm": None, "node_id": None, "observation_count": 0,
                "latest_observation": None, "history": [], "nodes": [], "alerts": []}

    nodes = list(db.execute(
        select(Node).where(Node.farm_id == farm_row.id).order_by(Node.created_at)
    ).scalars())
    q = select(Observation).where(Observation.farm_id == farm_row.id).order_by(
        Observation.timestamp.desc()
    )
    latest = db.execute(q.limit(1)).scalar_one_or_none()
    recent = list(db.execute(q.limit(20)).scalars())
    open_alerts = list(db.execute(
        select(Alert).where(Alert.farm_id == farm_row.id, Alert.resolved.is_(False))
        .order_by(Alert.created_at.desc()).limit(20)
    ).scalars())

    def dump(o: Observation) -> dict:
        return ObservationOut.model_validate(o).model_dump(mode="json")

    def node_json(n: Node) -> dict:
        health = db.get(NodeHealth, n.id)
        return {
            "id": n.id, "name": n.name, "location": n.location,
            "health": NodeHealthOut.model_validate(health).model_dump(mode="json") if health else None,
        }

    return {
        "farm": {"id": farm_row.id, "name": farm_row.name},
        "node_id": nodes[0].id if nodes else None,
        "observation_count": db.query(Observation).filter(
            Observation.farm_id == farm_row.id
        ).count(),
        "latest_observation": dump(latest) if latest else None,
        "history": [dump(o) for o in recent],
        "nodes": [node_json(n) for n in nodes],
        "alerts": [AlertOut.model_validate(a).model_dump(mode="json") for a in open_alerts],
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
