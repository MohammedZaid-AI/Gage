"""Gage backend entrypoint. Run: uvicorn backend.main:app --reload"""
import asyncio
import logging
import mimetypes
from pathlib import Path

# Force correct static MIME types. On some Windows machines the registry maps
# .css/.js to text/plain, which makes Chrome refuse the stylesheet (strict MIME
# checking) and render the whole app unstyled. Registering here is machine-independent.
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/javascript", ".js")

# Configure logging before importing anything that logs at import time (the AI
# providers load models then, and their startup messages would otherwise be lost).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# Verify TLS against the operating system's certificate store rather than
# Python's bundled one. Antivirus HTTPS scanning (e.g. Avast Web Shield)
# re-signs traffic with a root that Windows trusts but certifi does not, which
# otherwise makes every Groq / Sarvam / Hugging Face call fail certificate
# verification. Verification stays ON; only the trust source changes.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # optional: falls back to certifi
    pass

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.config import get_settings, require_secure_settings  # noqa: E402

# Fail loudly at import, before anything is served, if tokens would be forgeable.
require_secure_settings()

from backend.core.security import decode_access_token  # noqa: E402
from backend.database import SessionLocal, get_db, init_db  # noqa: E402
from backend.dependencies import get_current_farmer  # noqa: E402
from backend.models import Alert, Farm, Farmer, Node, NodeHealth, Observation  # noqa: E402
from backend.realtime import broadcaster  # noqa: E402
from backend.routers import (  # noqa: E402
    alerts as alerts_router,
    auth,
    chat,
    dataset,
    farm,
    farm_intel,
    node as node_router,
    observation,
    voice,
)
from backend.schemas import AlertOut, NodeHealthOut, ObservationOut  # noqa: E402
from backend.seed import seed_demo  # noqa: E402
from backend.services import alerts  # noqa: E402


app = FastAPI(title="Gage", description="AI agricultural field assistant")

app.include_router(auth.router)
app.include_router(alerts_router.router)
app.include_router(farm.router)
app.include_router(farm_intel.router)
app.include_router(node_router.router)
app.include_router(observation.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(dataset.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # Build the retrieval index now so the first farmer question is not slow.
    from backend.ai import knowledge

    knowledge.warm_up()
    if get_settings().seed_demo:
        with SessionLocal() as db:
            seed_demo(db)
    # Close alerts that newer readings already show are over (heals alerts left
    # open from before auto-resolution existed).
    with SessionLocal() as db:
        closed = alerts.reconcile_open_alerts(db)
        if closed:
            db.commit()
            logging.getLogger("gage.alerts").info("startup: resolved %d stale alert(s)", len(closed))


def _offline_tick() -> list[tuple[int, str, dict]]:
    """One offline check (blocking DB work, run in a worker thread). Returns the
    (owner farmer id, event, payload) messages to push to dashboards."""
    events = []
    with SessionLocal() as db:
        raised = alerts.evaluate_offline(db)
        db.commit()
        for a in raised:
            node = db.get(Node, a.node_id)
            owner = node.farm.farmer_id
            health = NodeHealthOut.model_validate(db.get(NodeHealth, node.id)).model_dump(mode="json")
            events.append((owner, "node_health", {"node_id": node.id, **health}))
            events.append((owner, "alert", AlertOut.model_validate(a).model_dump(mode="json")))
    return events


async def _offline_watch() -> None:
    """Background timer: mark nodes that have gone silent as offline, every
    OFFLINE_CHECK_SECONDS, whether or not anyone is looking at a dashboard."""
    log = logging.getLogger("gage.offline")
    interval = get_settings().offline_check_seconds
    log.info("offline watcher started: every %ds, offline after %ds silence",
             interval, get_settings().offline_seconds)
    while True:
        try:
            for owner, event, payload in await run_in_threadpool(_offline_tick):
                await broadcaster.broadcast(event, payload, owner)
        except Exception:  # never let one bad tick stop the watcher
            log.exception("offline check failed")
        await asyncio.sleep(interval)


@app.on_event("startup")
async def _start_background_tasks() -> None:
    app.state.offline_task = asyncio.create_task(_offline_watch())


@app.on_event("shutdown")
async def _stop_background_tasks() -> None:
    task = getattr(app.state, "offline_task", None)
    if task:
        task.cancel()


@app.get("/api/state")
def get_state(
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> dict:
    """Snapshot of the caller's first farm (WS handles live updates). Node
    online/offline status is kept current by the background offline watcher."""
    farm_row = db.execute(
        select(Farm).where(Farm.farmer_id == farmer.id).order_by(Farm.id).limit(1)
    ).scalar_one_or_none()
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
async def ws(websocket: WebSocket, token: str | None = None) -> None:
    """Live updates for one farmer. Browsers cannot set an Authorization header on
    a WebSocket, so the JWT comes as `?token=`. Invalid or missing -> the handshake
    is refused (HTTP 403) before any event can be sent."""
    farmer_id = decode_access_token(token) if token else None
    if farmer_id is not None:
        with SessionLocal() as db:
            if db.get(Farmer, farmer_id) is None:
                farmer_id = None
    if farmer_id is None:
        await websocket.close(code=1008)  # policy violation
        return
    await websocket.accept()
    await broadcaster.connect(websocket, farmer_id)
    try:
        while True:
            await websocket.receive_text()  # keep the socket open; inbound is ignored
    except WebSocketDisconnect:
        await broadcaster.disconnect(websocket)


@app.get("/storage/images/{filename}")
def observation_image(
    filename: str,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> FileResponse:
    """An uploaded field photo, only for the farmer whose farm captured it. 404
    (not 403) for anyone else, so file names cannot be probed."""
    name = Path(filename).name  # no path traversal
    owned = db.execute(
        select(Observation.id)
        .join(Farm, Farm.id == Observation.farm_id)
        .where(Farm.farmer_id == farmer.id,
               Observation.image_path.endswith("/" + name, autoescape=True))
        .limit(1)
    ).first()
    path = Path(get_settings().image_dir) / name
    if owned is None or not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


# --- static frontend ---
_ROOT = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=_ROOT / "frontend"), name="static")


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(_ROOT / "frontend" / "dashboard.html")
