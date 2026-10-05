"""FlyBrain sensor-pattern anomaly detection, per farm (see backend/ai/flybrain.py).

For each farm:
- Clean the history first: rows from a disconnected sensor (soil moisture
  exactly 0 for FLYBRAIN_ZERO_RUN+ consecutive readings, or every channel 0)
  are left out. Fewer than FLYBRAIN_MIN_CLEAN_ROWS clean rows -> no baseline,
  nothing flagged. A new reading with soil moisture 0 is not scored.
- Normalise each channel (temperature, humidity, soil moisture) against that
  farm's OWN minimum and maximum over its clean history.
- "Normal" readings are the farm's readings that trip no alert threshold.
  From those, a deterministic sample of FLYBRAIN_BASELINE_SIZE fits the
  baseline network response, and a separate held-out sample of
  FLYBRAIN_HELDOUT_SIZE is scored to calibrate the threshold: the
  FLYBRAIN_THRESHOLD_PERCENTILE of those scores. No fixed threshold.
- The baseline is refitted once every FLYBRAIN_REFIT_HOURS; a farm's new
  readings are scored at most once every FLYBRAIN_SCORE_INTERVAL_MINUTES.
- Scoring is queued on one background thread, and the simulation itself runs in
  a separate worker process, so it never holds the server's interpreter lock
  (it slowed sensor uploads when it ran in-process).
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
                "malecns_v1": "real MaleCNS v1.0 connectome",
                "malecns_v1_no_positions": "real MaleCNS v1.0 connections (without synapse "
                                           "positions)"}


def _compiled_name(compiled_dir: str) -> str:
    """'malecns_v1', or 'malecns_v1_no_positions' when the compiled graph was
    built without the synapse-point table (read from flycns's manifest)."""
    import json
    from pathlib import Path

    manifest = json.loads((Path(compiled_dir) / "manifest.json").read_text(encoding="utf-8"))
    keys = {src.get("key") for src in manifest.get("sources", [])}
    return "malecns_v1" if "synapses" in keys else "malecns_v1_no_positions"


def _engine(graph_name: str) -> str:
    """flycns simulation engine: FLYBRAIN_ENGINE, or for 'auto' the GPU (torch)
    for the real graph when CUDA is available, else the NumPy reference."""
    choice = get_settings().flybrain_engine
    if choice in ("numpy", "torch"):
        return choice
    if graph_name.startswith("malecns"):
        try:
            import torch

            if torch.cuda.is_available():
                return "torch"
        except ImportError:
            pass
    return "numpy"


def _graph_spec() -> tuple[tuple, str]:
    """(spec the worker builds the graph from, graph name). The real graph only
    when FLYBRAIN_GRAPH=malecns; the worker compiles it on first use."""
    s = get_settings()
    if s.flybrain_graph == "malecns":
        from pathlib import Path

        compiled = Path(s.flybrain_compiled_dir) / "manifest.json"
        name = _compiled_name(s.flybrain_compiled_dir) if compiled.exists() else "malecns_v1_no_positions"
        return ("malecns", s.flybrain_raw_dir, s.flybrain_compiled_dir), name
    return ("synthetic",), "synthetic"


_pool = None


def _worker():
    """The single FlyBrain worker process (created on first use)."""
    global _pool
    if _pool is None:
        from concurrent.futures import ProcessPoolExecutor

        _pool = ProcessPoolExecutor(max_workers=1)
    return _pool


def _in_worker(fn, *args):
    """Run backend.ai.flybrain_worker.fn(*args) in the worker process; restart
    the worker once if it died."""
    global _pool
    from concurrent.futures.process import BrokenProcessPool

    from backend.ai import flybrain_worker

    try:
        return _worker().submit(getattr(flybrain_worker, fn), *args).result()
    except BrokenProcessPool:
        logger.warning("FlyBrain worker process died; restarting it")
        _pool = None
        return _worker().submit(getattr(flybrain_worker, fn), *args).result()


@dataclass
class FarmBaseline:
    rates: np.ndarray        # baseline mean firing rate per neuron
    std: np.ndarray          # baseline spread per neuron
    graph_spec: tuple
    engine: str
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
_fit_info: dict[int, dict] = {}            # last fit attempt per farm: counts, reason
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
                                _compiled_name(s.flybrain_compiled_dir))
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


def _all_zero(r) -> bool:
    return all(getattr(r, ch) == 0 for ch in CHANNELS)


def clean_rows(history: list) -> tuple[list, dict]:
    """Drop rows from a disconnected sensor: every channel 0, or soil moisture
    exactly 0 for FLYBRAIN_ZERO_RUN or more consecutive readings. `history`
    must be in time order. Returns (clean rows, counts)."""
    run_min = get_settings().flybrain_zero_run
    bad = [_all_zero(r) for r in history]
    i = 0
    while i < len(history):
        if history[i].soil_moisture == 0:
            j = i
            while j < len(history) and history[j].soil_moisture == 0:
                j += 1
            if j - i >= run_min:
                for k in range(i, j):
                    bad[k] = True
            i = j
        else:
            i += 1
    clean = [r for r, b in zip(history, bad) if not b]
    counts = {"history": len(history), "clean": len(clean), "excluded": len(history) - len(clean),
              "all_zero": sum(_all_zero(r) for r in history),
              "soil_zero_runs": sum(bad) - sum(_all_zero(r) for r in history)}
    return clean, counts


def fit_farm(db: Session, farm_id: int) -> FarmBaseline | None:
    """Fit and calibrate this farm's baseline from its own CLEAN history. None if
    there are fewer than FLYBRAIN_MIN_CLEAN_ROWS clean rows, or too few normal
    ones; then nothing is flagged for this farm. The simulations run in the
    FlyBrain worker process (backend/ai/flybrain_worker.py)."""
    s = get_settings()
    history = list(db.execute(
        select(SensorReading).where(
            SensorReading.farm_id == farm_id, SensorReading.temperature.is_not(None),
            SensorReading.humidity.is_not(None), SensorReading.soil_moisture.is_not(None),
        ).order_by(SensorReading.timestamp)
    ).scalars())
    clean, counts = clean_rows(history)
    normal = [r for r in clean if _is_normal(r)]
    counts["normal"] = len(normal)
    need = s.flybrain_baseline_size + s.flybrain_heldout_size
    logger.info("farm %d: FlyBrain data cleaning: %d rows before, %d after (%d excluded: %d "
                "in soil-moisture-zero runs of >= %d, %d all-zero); %d clean normal rows",
                farm_id, counts["history"], counts["clean"], counts["excluded"],
                counts["soil_zero_runs"], s.flybrain_zero_run, counts["all_zero"], len(normal))
    if len(clean) < s.flybrain_min_clean_rows or len(normal) < need:
        reason = (f"not enough clean history: {len(clean)} clean rows (need "
                  f"{s.flybrain_min_clean_rows}), {len(normal)} clean normal rows (need {need})")
        _fit_info[farm_id] = {**counts, "fitted": False, "reason": reason}
        logger.info("farm %d: FlyBrain %s; nothing will be flagged", farm_id, reason)
        return None
    _fit_info[farm_id] = {**counts, "fitted": True, "reason": None}
    history = clean   # the normalisation range comes from clean rows only
    mins = {ch: min(getattr(r, ch) for r in history) for ch in CHANNELS}
    maxs = {ch: max(getattr(r, ch) for r in history) for ch in CHANNELS}
    order = np.random.default_rng(farm_id).permutation(len(normal))
    base = [normal[i] for i in order[:s.flybrain_baseline_size]]
    heldout = [normal[i] for i in order[s.flybrain_baseline_size:need]]

    spec, graph_name = _graph_spec()
    args = ([_normalise(r, mins, maxs) for r in base], [_normalise(r, mins, maxs) for r in heldout])
    try:
        fitted = _in_worker("fit", spec, s.flybrain_sim_steps, _engine(graph_name), *args)
    except Exception:
        if spec[0] == "synthetic":
            raise
        logger.exception("FLYBRAIN_GRAPH=malecns but the real connectome could not be used; "
                         "using the synthetic test graph")
        spec, graph_name = ("synthetic",), "synthetic"
        fitted = _in_worker("fit", spec, s.flybrain_sim_steps, _engine(graph_name), *args)
    scores = fitted["heldout_scores"]
    threshold = float(np.percentile(scores, s.flybrain_threshold_percentile))
    bl = FarmBaseline(fitted["rates"], fitted["std"], spec, _engine(graph_name), mins, maxs,
                      threshold, s.flybrain_threshold_percentile, graph_name,
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
    if reading.soil_moisture == 0 or _all_zero(reading):
        # A disconnected sensor, not a field pattern: not scored (the soil alert
        # rule still reports it).
        logger.info("farm %d reading %s: soil moisture 0 (sensor likely disconnected); "
                    "not scored", reading.farm_id, reading.id)
        return None
    bl = _baseline(db, reading.farm_id)
    if bl is None:
        return None
    score = _in_worker("score", bl.graph_spec, get_settings().flybrain_sim_steps, bl.engine,
                       bl.rates, bl.std, _normalise(reading, bl.mins, bl.maxs))
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
        # Last fit attempt: rows before/after cleaning, and why nothing is flagged.
        "data": _fit_info.get(farm_id),
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


def shutdown() -> None:
    """Stop the FlyBrain worker process (called on server shutdown)."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
