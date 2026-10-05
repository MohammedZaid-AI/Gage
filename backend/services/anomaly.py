"""FlyBrain sensor-pattern anomaly detection, per farm (see backend/ai/flybrain.py).

For each farm:
- Normalise each channel (temperature, humidity, soil moisture) against that
  farm's OWN minimum and maximum over its whole SensorReading history.
- "Normal" readings are the farm's readings that trip no alert threshold.
  From those, a deterministic sample of FLYBRAIN_BASELINE_SIZE fits the
  baseline network response, and a separate held-out sample of
  FLYBRAIN_HELDOUT_SIZE is scored to calibrate the threshold: the
  FLYBRAIN_THRESHOLD_PERCENTILE of those scores. No fixed threshold.
- The baseline is refitted once every FLYBRAIN_REFIT_HOURS; a farm's new
  readings are scored at most once every FLYBRAIN_SCORE_INTERVAL_MINUTES.
- All simulation runs on one dedicated background thread: requests never wait.
- A reading scoring above the threshold raises an `anomaly` alert; a later
  normal score resolves it. Every score is stored (AnomalyScore) and the
  latest one is described to the answering model in plain words.

The graph is synthetic unless FLYBRAIN_GRAPH=malecns and a compiled MaleCNS v1.0
connectome exists; every output says which one was actually used.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import AnomalyScore, SensorReading, _now
from backend.services import alerts

logger = logging.getLogger("gage.flybrain")

CHANNELS = ("temperature", "humidity", "soil_moisture")
GRAPH_LABELS = {"synthetic": "synthetic test graph (not the real fly connectome)",
                "malecns_v1": "real MaleCNS v1.0 connectome"}


@dataclass
class FarmBaseline:
    detector: object
    mins: dict
    maxs: dict
    threshold: float
    percentile: float
    graph: str
    fitted_at: datetime
    n_history: int
    n_normal: int
    n_baseline: int
    heldout_scores: list = field(default_factory=list)


_graph_cache: tuple | None = None          # (graph tuple, graph name)
_baselines: dict[int, FarmBaseline] = {}
_last_scored: dict[int, datetime] = {}
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flybrain")


def _graph():
    """Build (once) the graph to simulate on, and say which one it is."""
    global _graph_cache
    if _graph_cache is None:
        from backend.ai import flybrain

        s = get_settings()
        if s.flybrain_graph == "malecns":
            try:
                _graph_cache = (flybrain.load_real_malecns(s.flybrain_raw_dir, s.flybrain_compiled_dir),
                                "malecns_v1")
            except Exception:
                logger.exception("FLYBRAIN_GRAPH=malecns but the real connectome could not be "
                                 "loaded; using the synthetic test graph")
        if _graph_cache is None:
            _graph_cache = (flybrain.build_synthetic_graph(n_neurons=2000, n_edges=15000), "synthetic")
        logger.info("flybrain graph: %s (%d neurons)", _graph_cache[1], _graph_cache[0][3])
    return _graph_cache


def _is_normal(r: SensorReading) -> bool:
    s = get_settings()
    return (r.humidity <= s.humidity_max and r.soil_moisture >= s.soil_moisture_min
            and r.temperature <= s.temperature_max)


def _normalise(r, mins: dict, maxs: dict) -> dict:
    out = {}
    for ch in CHANNELS:
        span = maxs[ch] - mins[ch]
        out[ch] = (getattr(r, ch) - mins[ch]) / span if span > 0 else 0.5
    return out


def fit_farm(db: Session, farm_id: int) -> FarmBaseline | None:
    """Fit and calibrate this farm's baseline from its own history. None if the
    farm does not have enough normal readings yet."""
    from backend.ai import flybrain

    s = get_settings()
    history = list(db.execute(
        select(SensorReading).where(
            SensorReading.farm_id == farm_id, SensorReading.temperature.is_not(None),
            SensorReading.humidity.is_not(None), SensorReading.soil_moisture.is_not(None),
        ).order_by(SensorReading.timestamp)
    ).scalars())
    normal = [r for r in history if _is_normal(r)]
    need = s.flybrain_baseline_size + s.flybrain_heldout_size
    if len(normal) < need:
        logger.info("farm %d: %d normal readings, need %d to fit a FlyBrain baseline",
                    farm_id, len(normal), need)
        return None
    mins = {ch: min(getattr(r, ch) for r in history) for ch in CHANNELS}
    maxs = {ch: max(getattr(r, ch) for r in history) for ch in CHANNELS}
    order = np.random.default_rng(farm_id).permutation(len(normal))
    base = [normal[i] for i in order[:s.flybrain_baseline_size]]
    heldout = [normal[i] for i in order[s.flybrain_baseline_size:need]]

    graph, graph_name = _graph()
    det = flybrain.FlyBrainAnomalyDetector(
        graph, flybrain.SensorEncoder(n_neurons=graph[3]), sim_steps=s.flybrain_sim_steps)
    det.fit_baseline([_normalise(r, mins, maxs) for r in base])
    scores = [det.score(_normalise(r, mins, maxs))["anomaly_score"] for r in heldout]
    threshold = float(np.percentile(scores, s.flybrain_threshold_percentile))
    bl = FarmBaseline(det, mins, maxs, threshold, s.flybrain_threshold_percentile, graph_name,
                      _now(), len(history), len(normal), len(base), scores)
    logger.info("farm %d: FlyBrain baseline fitted on %s from %d normal readings; held-out "
                "scores %.3f..%.3f, threshold (p%g) %.3f", farm_id, graph_name, len(base),
                min(scores), max(scores), s.flybrain_threshold_percentile, threshold)
    return bl


def _baseline(db: Session, farm_id: int) -> FarmBaseline | None:
    bl = _baselines.get(farm_id)
    stale = bl is None or _now() - bl.fitted_at > timedelta(hours=get_settings().flybrain_refit_hours)
    if stale:
        fresh = fit_farm(db, farm_id)
        if fresh is not None:
            _baselines[farm_id] = bl = fresh
    return bl


def score_reading(db: Session, reading: SensorReading) -> AnomalyScore | None:
    """Score one reading against its farm's baseline, store the score, and raise
    or resolve the farm's anomaly alert. Caller commits. Blocking (simulation)."""
    if None in (reading.temperature, reading.humidity, reading.soil_moisture):
        return None
    bl = _baseline(db, reading.farm_id)
    if bl is None:
        return None
    result = bl.detector.score(_normalise(reading, bl.mins, bl.maxs))
    score = result["anomaly_score"]
    row = AnomalyScore(
        farm_id=reading.farm_id, node_id=reading.node_id, reading_id=reading.id,
        score=round(score, 4), threshold=round(bl.threshold, 4),
        is_anomalous=score > bl.threshold, graph=bl.graph,
    )
    db.add(row)
    if row.is_anomalous:
        alerts._raise(db, reading.farm_id, reading.node_id, "anomaly", "warning",
                      f"Unusual sensor pattern for this field (FlyBrain score {score:.2f} "
                      f"> threshold {bl.threshold:.2f}, {bl.graph} graph)", round(score, 4))
    else:
        for a in alerts._open(db, reading.node_id, "anomaly"):
            alerts.resolve(a, f"auto: sensor pattern back to normal (score {score:.2f})")
    logger.info("farm %d reading %s: FlyBrain score %.3f vs %.3f -> %s", reading.farm_id,
                reading.id, score, bl.threshold, "ANOMALY" if row.is_anomalous else "normal")
    return row


def _run(reading_id: int) -> None:
    try:
        with SessionLocal() as db:
            reading = db.get(SensorReading, reading_id)
            if reading is not None and score_reading(db, reading) is not None:
                db.commit()
    except Exception:
        logger.exception("FlyBrain scoring failed for reading %s", reading_id)


def schedule(farm_id: int, reading_id: int) -> bool:
    """Queue a reading for scoring unless this farm was scored recently. Returns
    whether it was queued. Never blocks the caller."""
    s = get_settings()
    if not s.flybrain_enabled:
        return False
    with _lock:
        last = _last_scored.get(farm_id)
        if last and _now() - last < timedelta(minutes=s.flybrain_score_interval_minutes):
            return False
        _last_scored[farm_id] = _now()
    _executor.submit(_run, reading_id)
    return True


def describe(score: AnomalyScore | None) -> str | None:
    """One plain sentence about the latest score, for the answering model."""
    if score is None:
        return None
    label = GRAPH_LABELS.get(score.graph, score.graph)
    if score.is_anomalous:
        return (f"The latest sensor reading scored {score.score:.2f} on the FlyBrain pattern "
                f"check, above this farm's own normal threshold of {score.threshold:.2f}: its "
                f"combination of temperature, humidity and soil moisture is unusual for this "
                f"field. This is a statistical flag from a {label} simulation, not a diagnosis.")
    return (f"The latest sensor reading scored {score.score:.2f} on the FlyBrain pattern check, "
            f"within this farm's normal range (threshold {score.threshold:.2f}; {label}).")


def status(db: Session, farm_id: int) -> dict:
    """API view: which graph, the calibration, and the latest score."""
    s = get_settings()
    bl = _baselines.get(farm_id)
    latest = db.execute(select(AnomalyScore).where(AnomalyScore.farm_id == farm_id)
                        .order_by(AnomalyScore.created_at.desc()).limit(1)).scalar_one_or_none()
    graph = bl.graph if bl else (latest.graph if latest else None)
    return {
        "enabled": s.flybrain_enabled,
        "graph": graph,
        "graph_description": GRAPH_LABELS.get(graph) if graph else "no baseline fitted yet",
        "baseline": None if bl is None else {
            "fitted_at": bl.fitted_at, "history_readings": bl.n_history,
            "normal_readings": bl.n_normal, "baseline_readings": bl.n_baseline,
            "heldout_readings": len(bl.heldout_scores),
            "threshold": round(bl.threshold, 4), "threshold_percentile": bl.percentile,
            "channel_min": bl.mins, "channel_max": bl.maxs,
        },
        "latest": None if latest is None else {
            "reading_id": latest.reading_id, "score": latest.score, "threshold": latest.threshold,
            "is_anomalous": latest.is_anomalous, "graph": latest.graph, "at": latest.created_at,
            "sentence": describe(latest),
        },
        "note": "The sensor-to-neuron encoding is a design choice, not a biologically "
                "validated mapping; scores are relative to this farm's own history.",
    }
