"""Part 4.1-4.3: FlyBrain on cleaned history (a copy of the real database)."""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, ".")
db_path = os.path.abspath("test_runs/_p4.db")
shutil.copy2("storage/observations.db", db_path)
os.environ["DATABASE_URL"] = "sqlite:///" + db_path.replace(os.sep, "/")
os.environ["LLM_PROVIDER"] = "mock"

import numpy as np  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import Alert, SensorReading  # noqa: E402
from backend.services import alerts, anomaly  # noqa: E402

init_db()
out = {}
with SessionLocal() as db:
    t = time.perf_counter()
    bl = anomaly.fit_farm(db, 1)
    out["fit_seconds"] = round(time.perf_counter() - t, 1)
    out["cleaning"] = anomaly._fit_info[1]
    print("cleaning:", out["cleaning"])
    if bl is None:
        print("NOT FITTED:", out["cleaning"]["reason"])
    else:
        hs = np.array(bl.heldout_scores)
        out["threshold"] = round(bl.threshold, 4)
        out["heldout"] = {"min": round(hs.min(), 4), "median": round(float(np.median(hs)), 4),
                          "p95": round(float(np.percentile(hs, 95)), 4), "max": round(hs.max(), 4)}
        out["channel_min"], out["channel_max"] = bl.mins, bl.maxs
        print(f"fit {out['fit_seconds']}s graph={bl.graph} baseline={bl.n_baseline} "
              f"held-out={len(hs)} threshold(p{bl.percentile:g})={bl.threshold:.4f} held-out={out['heldout']}")
        print("normalisation range (clean rows):", bl.mins, bl.maxs)
        anomaly._baselines[1] = bl
        for rid in (299, 534):
            r = db.get(SensorReading, rid)
            row = anomaly.score_reading(db, r)
            db.commit()
            out[f"reading_{rid}"] = {"temp": r.temperature, "humidity": r.humidity,
                                     "soil": r.soil_moisture, "score": row.score,
                                     "threshold": row.threshold, "anomalous": row.is_anomalous}
            print(f"reading {rid} ({r.temperature} C, {r.humidity} %, soil {r.soil_moisture} %): "
                  f"score {row.score:.4f} vs {row.threshold:.4f} -> "
                  f"{'ANOMALY' if row.is_anomalous else 'normal'}")

    # 4.3 Do the alert rules fire on zero readings? (rules NOT changed)
    zero = db.execute(select(SensorReading).where(SensorReading.farm_id == 1,
                                                  SensorReading.soil_moisture == 0).limit(1)).scalar_one()
    fired = alerts.evaluate_reading(db, zero)
    out["alert_rules_on_zero_reading"] = [(a.type, a.message) for a in fired]
    out["scored_zero_reading"] = anomaly.score_reading(db, zero) is not None
    db.rollback()
    hist = db.execute(select(func.count()).select_from(Alert).where(
        Alert.type == "soil_low", Alert.value == 0)).scalar_one()
    out["historical_soil_low_alerts_at_0"] = hist
    print("alert rules on a soil=0 reading:", out["alert_rules_on_zero_reading"] or "none fired",
          "| FlyBrain scored it:", out["scored_zero_reading"],
          "| soil_low alerts in DB with value 0:", hist)
    out["api_status"] = json.loads(json.dumps(anomaly.status(db, 1), default=str))
    print("API graph:", out["api_status"]["graph_description"])
json.dump(out, open("test_runs/part8_flybrain_worker.json", "w", encoding="utf-8"), indent=1, default=str)
