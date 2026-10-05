"""Farm intelligence endpoints: summary, timeline, health score.

Routers stay thin: they resolve ownership, call the Farm Context Engine and the
health-score service, and serialize. No context assembly or scoring here.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Farmer, Observation
from backend.schemas import (
    AlertOut,
    FarmSummaryOut,
    HealthOut,
    ObservationOut,
    SensorSnapshot,
    TrendOut,
)
from backend.services import anomaly, farm_context, health_score

router = APIRouter(prefix="/farm", tags=["farm-intelligence"])


def _health_out(hs) -> HealthOut:
    return HealthOut(score=hs.score, status=hs.status, reasons=hs.reasons)


@router.get("/{farm_id}/summary", response_model=FarmSummaryOut)
def farm_summary(
    farm_id: int,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> FarmSummaryOut:
    farm = owned_farm(db, farmer, farm_id)
    ctx = farm_context.build(db, farm)
    hs = health_score.compute(ctx)
    latest = ctx.latest
    return FarmSummaryOut(
        farm_id=farm.id,
        name=farm.name,
        crop_type=ctx.crop_type,
        location=ctx.location,
        health=_health_out(hs),
        last_observation_time=latest.timestamp if latest else None,
        sensor_snapshot=SensorSnapshot(
            temperature=latest.temperature if latest else None,
            humidity=latest.humidity if latest else None,
            soil_moisture=latest.soil_moisture if latest else None,
        ),
        trends=[TrendOut(
            metric=t.metric, current=t.current, previous=t.previous,
            delta=t.delta, direction=t.direction, unit=t.unit, days_ago=t.days_ago,
        ) for t in ctx.trends],
        active_alerts=[AlertOut.model_validate(a) for a in ctx.active_alerts],
        # The newest stored summary, not necessarily the newest observation's:
        # summaries are written by a background task on a new alert or at most
        # every SUMMARY_INTERVAL_MINUTES (observation_service.generate_summary),
        # so most observations have none. No LLM call on a dashboard poll.
        ai_summary=db.execute(
            select(Observation.ai_summary)
            .where(Observation.farm_id == farm.id, Observation.ai_summary.is_not(None))
            .order_by(Observation.timestamp.desc()).limit(1)
        ).scalar_one_or_none(),
        latest_observation=ObservationOut.model_validate(latest) if latest else None,
    )


@router.get("/{farm_id}/timeline", response_model=list[ObservationOut])
def farm_timeline(
    farm_id: int,
    limit: int = 50,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> list:
    farm = owned_farm(db, farmer, farm_id)
    obs = list(db.execute(
        select(Observation).where(Observation.farm_id == farm.id)
        .order_by(Observation.timestamp.desc()).limit(limit)
    ).scalars())
    return [ObservationOut.model_validate(o) for o in obs]


@router.get("/{farm_id}/anomaly")
def farm_anomaly(
    farm_id: int,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> dict:
    """FlyBrain sensor-pattern check: which graph was used (synthetic or the real
    MaleCNS connectome), this farm's calibrated threshold, and the latest score."""
    farm = owned_farm(db, farmer, farm_id)
    return anomaly.status(db, farm.id)


@router.get("/{farm_id}/health", response_model=HealthOut)
def farm_health(
    farm_id: int,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> HealthOut:
    farm = owned_farm(db, farmer, farm_id)
    ctx = farm_context.build(db, farm)
    return _health_out(health_score.compute(ctx))
