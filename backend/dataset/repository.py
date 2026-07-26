"""DatasetRepository — all dataset queries live here (filtering, stats, lookups).
The service and exporter go through this; routers never query directly.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.dataset.models import DatasetEntry, DatasetExport, EXPORTED


@dataclass
class DatasetFilters:
    farm_id: int | None = None
    crop_type: str | None = None
    min_quality: int | None = None
    status: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class DatasetRepository:
    @staticmethod
    def get(db: Session, entry_id: int) -> DatasetEntry | None:
        return db.get(DatasetEntry, entry_id)

    @staticmethod
    def get_by_observation(db: Session, observation_id: str) -> DatasetEntry | None:
        return db.execute(
            select(DatasetEntry).where(DatasetEntry.observation_id == observation_id)
        ).scalar_one_or_none()

    @staticmethod
    def _apply(stmt, farm_ids: list[int], f: DatasetFilters):
        stmt = stmt.where(DatasetEntry.farm_id.in_(farm_ids))
        if f.farm_id is not None:
            stmt = stmt.where(DatasetEntry.farm_id == f.farm_id)
        if f.crop_type:
            stmt = stmt.where(DatasetEntry.crop_type == f.crop_type)
        if f.min_quality is not None:
            stmt = stmt.where(DatasetEntry.quality_score >= f.min_quality)
        if f.status:
            stmt = stmt.where(DatasetEntry.status == f.status)
        if f.date_from:
            stmt = stmt.where(DatasetEntry.timestamp >= f.date_from)
        if f.date_to:
            stmt = stmt.where(DatasetEntry.timestamp <= f.date_to)
        return stmt

    @classmethod
    def list(cls, db: Session, farm_ids: list[int], f: DatasetFilters,
             limit: int | None = None) -> list[DatasetEntry]:
        if not farm_ids:
            return []
        stmt = cls._apply(select(DatasetEntry), farm_ids, f).order_by(
            DatasetEntry.timestamp.desc()
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(db.execute(stmt).scalars())

    @classmethod
    def stats(cls, db: Session, farm_ids: list[int]) -> dict:
        if not farm_ids:
            return {"dataset_entries": 0, "exported_entries": 0, "average_quality": 0,
                    "total_observations": 0, "crop_distribution": {},
                    "farm_distribution": {}, "today_records": 0, "daily_rate": {},
                    "export_history": []}
        scope = DatasetEntry.farm_id.in_(farm_ids)
        entries = list(db.execute(select(DatasetEntry).where(scope)).scalars())
        total = len(entries)
        exported = sum(1 for e in entries if e.status == EXPORTED)
        avg_q = round(sum(e.quality_score for e in entries) / total, 1) if total else 0

        def day(e: DatasetEntry) -> str:
            return e.timestamp.strftime("%Y-%m-%d")

        today = datetime.utcnow().strftime("%Y-%m-%d")
        last7 = {(datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d"): 0
                 for i in range(7)}
        for e in entries:
            d = day(e)
            if d in last7:
                last7[d] += 1

        exports = list(db.execute(
            select(DatasetExport).order_by(DatasetExport.created_at.desc()).limit(10)
        ).scalars())

        return {
            "total_observations": db.scalar(
                select(func.count()).select_from(DatasetEntry).where(scope)
            ),
            "dataset_entries": total,
            "exported_entries": exported,
            "average_quality": avg_q,
            "crop_distribution": dict(Counter(e.crop_type for e in entries)),
            "farm_distribution": dict(Counter(e.farm_id for e in entries)),
            "today_records": sum(1 for e in entries if day(e) == today),
            "daily_rate": dict(sorted(last7.items())),
            "export_history": [
                {"version": x.dataset_version, "fmt": x.fmt, "records": x.record_count,
                 "checksum": x.checksum[:12], "created_at": x.created_at.isoformat()}
                for x in exports
            ],
        }
