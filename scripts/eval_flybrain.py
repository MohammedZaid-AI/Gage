"""Compare FlyBrain with two standard anomaly detectors on this farm's data.

    python scripts/eval_flybrain.py [--farm 1] [--out test_runs/part4_eval.json]

Reads the farm's sensor history (read-only), cleans it exactly as the live
service does (services/anomaly.clean_rows), and keeps the clean NORMAL readings
(no alert rule tripped). Then, with a fixed seed:
- the same 40 readings fit all three detectors (as the live baseline does);
- the remaining normal readings are the negatives;
- anomalies are injected into copies of held-out normal readings:
    heat spike     temperature +6 C
    drought        soil moisture x0.3, temperature +2 C, humidity -15 points
    humidity jump  humidity +20 points (capped at 100)
- every reading is normalised the same way (the farm's clean min/max).

Detectors: FlyBrain (the live one, same graph and settings), IsolationForest
(scikit-learn, a development-only dependency), and a z-score baseline (largest
absolute per-channel z-score against the fit readings).
Metrics: AUROC, and recall at a 1 % false-alarm rate (threshold = 99th
percentile of each detector's scores on the normal test readings).
"""
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


@dataclass
class Reading:
    temperature: float
    humidity: float
    soil_moisture: float


INJECTIONS = {
    "heat_spike": lambda r: Reading(r.temperature + 6, r.humidity, r.soil_moisture),
    "drought": lambda r: Reading(r.temperature + 2, max(0.0, r.humidity - 15), r.soil_moisture * 0.3),
    "humidity_jump": lambda r: Reading(r.temperature, min(100.0, r.humidity + 20), r.soil_moisture),
}


def recall_at_fpr(neg: np.ndarray, pos: np.ndarray, fpr: float = 0.01) -> tuple[float, float]:
    thr = float(np.percentile(neg, 100 * (1 - fpr)))
    return float(np.mean(pos > thr)), thr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--farm", type=int, default=1)
    ap.add_argument("--per-type", type=int, default=40, help="anomalies injected per type")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="test_runs/part4_eval.json")
    args = ap.parse_args()

    from sklearn.ensemble import IsolationForest
    from sklearn.metrics import roc_auc_score
    from sqlalchemy import select

    from backend.ai import flybrain
    from backend.config import get_settings
    from backend.database import SessionLocal
    from backend.models import SensorReading
    from backend.services import anomaly

    s = get_settings()
    with SessionLocal() as db:
        history = list(db.execute(select(SensorReading).where(
            SensorReading.farm_id == args.farm, SensorReading.temperature.is_not(None),
            SensorReading.humidity.is_not(None), SensorReading.soil_moisture.is_not(None),
        ).order_by(SensorReading.timestamp)).scalars())
        clean, counts = anomaly.clean_rows(history)
        normal = [Reading(r.temperature, r.humidity, r.soil_moisture)
                  for r in clean if anomaly._is_normal(r)]
    mins = {ch: min(getattr(r, ch) for r in clean) for ch in anomaly.CHANNELS}
    maxs = {ch: max(getattr(r, ch) for r in clean) for ch in anomaly.CHANNELS}
    print(f"history {counts['history']} rows, clean {counts['clean']}, clean normal {len(normal)}")

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(normal))
    n_fit = s.flybrain_baseline_size
    fit = [normal[i] for i in order[:n_fit]]
    test_normal = [normal[i] for i in order[n_fit:]]
    sources = [test_normal[i] for i in rng.choice(len(test_normal), args.per_type, replace=False)]
    anomalies = {name: [f(r) for r in sources] for name, f in INJECTIONS.items()}

    def vec(r) -> np.ndarray:
        return np.array(list(anomaly._normalise(r, mins, maxs).values()))

    X_fit = np.array([vec(r) for r in fit])
    test = [(r, 0, "normal") for r in test_normal] + [
        (r, 1, name) for name, rows in anomalies.items() for r in rows]
    X_test = np.array([vec(r) for r, _, _ in test])
    y = np.array([lab for _, lab, _ in test])
    kinds = np.array([k for _, _, k in test])

    scores = {}
    graph, graph_name = anomaly._graph()
    det = flybrain.FlyBrainAnomalyDetector(graph, flybrain.SensorEncoder(n_neurons=graph[3]),
                                           sim_steps=s.flybrain_sim_steps)
    t = time.perf_counter()
    det.fit_baseline([anomaly._normalise(r, mins, maxs) for r in fit])
    scores["flybrain"] = np.array([det.score(anomaly._normalise(r, mins, maxs))["anomaly_score"]
                                   for r, _, _ in test])
    fb_seconds = time.perf_counter() - t

    iso = IsolationForest(n_estimators=300, random_state=args.seed).fit(X_fit)
    scores["isolation_forest"] = -iso.score_samples(X_test)       # higher = more anomalous

    mu, sd = X_fit.mean(axis=0), X_fit.std(axis=0) + 1e-9
    scores["z_score"] = np.abs((X_test - mu) / sd).max(axis=1)

    results = {}
    neg_mask = y == 0
    for name, sc in scores.items():
        rec, thr = recall_at_fpr(sc[neg_mask], sc[~neg_mask])
        per_type = {k: recall_at_fpr(sc[neg_mask], sc[kinds == k])[0] for k in INJECTIONS}
        results[name] = {"auroc": round(float(roc_auc_score(y, sc)), 4),
                         "recall_at_1pct_fpr": round(rec, 4), "threshold": round(thr, 4),
                         "recall_by_type": {k: round(v, 4) for k, v in per_type.items()}}
        print(f"{name:<17} AUROC {results[name]['auroc']:.3f}  recall@1%FPR "
              f"{results[name]['recall_at_1pct_fpr']:.3f}  by type {results[name]['recall_by_type']}")

    report = {
        "farm": args.farm, "graph": graph_name, "data": counts, "clean_normal": len(normal),
        "fit_readings": n_fit, "normal_test_readings": len(test_normal),
        "anomalies_per_type": args.per_type, "injections": list(INJECTIONS),
        "flybrain_seconds_total": round(fb_seconds, 1),
        "flybrain_seconds_per_reading": round(fb_seconds / (n_fit + len(test)), 3),
        "results": results,
        "note": ("Recall at 1% FPR rests on the 99th percentile of "
                 f"{len(test_normal)} normal test readings, so it is coarse."),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
