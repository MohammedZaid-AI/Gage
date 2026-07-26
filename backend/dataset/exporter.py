"""Exporter — writes dataset entries to JSONL / CSV (Parquet optional), versioned
with a checksum, and records the run in dataset_exports. Exported entries move to
the EXPORTED state.
"""
import csv
import hashlib
import io
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.dataset.models import ARCHIVED, EXPORTED, DatasetEntry, DatasetExport
from backend.dataset.repository import DatasetFilters, DatasetRepository

logger = logging.getLogger("gage.dataset.export")

_DATASET_DIR = Path("./storage/datasets")
_FORMATS = ("jsonl", "csv", "parquet")


def _row(e: DatasetEntry) -> dict:
    """The canonical training record for one dataset entry."""
    return {
        "dataset_id": e.id,
        "observation_id": e.observation_id,
        "farm_id": e.farm_id,
        "node_id": e.node_id,
        "crop_type": e.crop_type,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "gps_lat": e.gps_lat,
        "gps_long": e.gps_long,
        "temperature": e.temperature,
        "humidity": e.humidity,
        "soil_moisture": e.soil_moisture,
        "vision_summary": e.vision_summary,
        "ai_summary": e.ai_summary,
        "active_alerts": list(e.active_alerts or []),
        "labels": list(e.labels or []),
        "image_path": e.image_path,
        "conversation_reference": e.conversation_reference,
        "weather_reference": e.weather_reference,
        "quality_score": e.quality_score,
        "status": e.status,
    }


def _write_jsonl(rows: list[dict]) -> bytes:
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")


def _write_csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for r in rows:
        flat = {k: ("|".join(map(str, v)) if isinstance(v, list) else v)
                for k, v in r.items()}
        writer.writerow(flat)
    return buf.getvalue().encode("utf-8")


def _write_parquet(rows: list[dict]) -> bytes:
    try:
        import pyarrow as pa  # optional dependency
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ValueError("parquet export requires pyarrow (not installed)") from exc
    cols = {k: [r[k] for r in rows] for k in (rows[0].keys() if rows else [])}
    # lists aren't primitive columns; serialize to JSON strings for portability.
    for k, vals in cols.items():
        if vals and isinstance(vals[0], list):
            cols[k] = [json.dumps(v) for v in vals]
    buf = io.BytesIO()
    pq.write_table(pa.table(cols), buf)
    return buf.getvalue()


_WRITERS = {"jsonl": _write_jsonl, "csv": _write_csv, "parquet": _write_parquet}


class Exporter:
    @staticmethod
    def export(db: Session, farm_ids: list[int], filters: DatasetFilters,
               fmt: str = "jsonl") -> DatasetExport:
        fmt = fmt.lower()
        if fmt not in _FORMATS:
            raise ValueError(f"unsupported format {fmt!r}; use one of {_FORMATS}")

        entries = DatasetRepository.list(db, farm_ids, filters)
        rows = [_row(e) for e in entries]
        data = _WRITERS[fmt](rows)

        _DATASET_DIR.mkdir(parents=True, exist_ok=True)
        version = "v" + datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        path = _DATASET_DIR / f"dataset_{version}.{fmt}"
        path.write_bytes(data)
        checksum = hashlib.sha256(data).hexdigest()

        for e in entries:  # advance state (never touch archived rows)
            if e.status != ARCHIVED:
                e.status = EXPORTED

        export = DatasetExport(
            dataset_version=version, fmt=fmt, record_count=len(rows),
            filters_used=_filters_dict(filters), checksum=checksum,
            path=path.as_posix(),
        )
        db.add(export)
        db.commit()
        db.refresh(export)
        logger.info("exported %d records -> %s (%s)", len(rows), path.name, checksum[:12])
        return export


def _filters_dict(f: DatasetFilters) -> dict:
    return {
        "farm_id": f.farm_id, "crop_type": f.crop_type, "min_quality": f.min_quality,
        "status": f.status,
        "date_from": f.date_from.isoformat() if f.date_from else None,
        "date_to": f.date_to.isoformat() if f.date_to else None,
    }
