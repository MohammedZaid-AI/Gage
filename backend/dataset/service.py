"""DatasetService — orchestrates entry creation from observations, plus
conversation linking. This is the composition point of the Dataset Builder; it
uses the scorer, labeller, validator, and repository. No AI imports.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dataset.labels import LabelGenerator
from backend.dataset.models import DatasetEntry
from backend.dataset.quality import QualityScorer
from backend.dataset.repository import DatasetRepository
from backend.dataset.validators import Validators
from backend.models import Alert, Conversation, Farm, Observation

logger = logging.getLogger("gage.dataset")


class DatasetService:
    @staticmethod
    def build_from_observation(db: Session, obs: Observation) -> DatasetEntry:
        """Create or update the single dataset entry for an observation. Idempotent:
        safe to call every time the observation changes (e.g. sensor-only -> merged)."""
        entry = DatasetRepository.get_by_observation(db, obs.id) or DatasetEntry(
            observation_id=obs.id
        )
        farm = db.get(Farm, obs.farm_id)
        active_alerts = [a.type for a in db.execute(
            select(Alert).where(Alert.farm_id == obs.farm_id, Alert.resolved.is_(False))
        ).scalars()]

        entry.farm_id = obs.farm_id
        entry.node_id = obs.node_id
        entry.crop_type = farm.crop_type if farm else "unknown"
        entry.timestamp = obs.timestamp
        entry.gps_lat, entry.gps_long = obs.gps_lat, obs.gps_long
        entry.temperature = obs.temperature
        entry.humidity = obs.humidity
        entry.soil_moisture = obs.soil_moisture
        entry.vision_summary = obs.vision_summary
        entry.ai_summary = obs.ai_summary
        entry.image_path = obs.image_path
        entry.active_alerts = active_alerts

        q = QualityScorer.score(obs)
        entry.quality_score = q.score
        entry.quality_reason = q.reason
        entry.labels = LabelGenerator.generate(obs, active_alerts)
        entry.status = Validators.validate(entry)

        db.add(entry)
        db.commit()
        db.refresh(entry)
        logger.info("dataset entry for obs %s (q=%d, %s, labels=%s)",
                    obs.id, entry.quality_score, entry.status, entry.labels)
        return entry

    @staticmethod
    def link_recent_conversations(db: Session, farm_id: int) -> int:
        """Attach each conversation to the dataset entry of the observation that was
        latest when it was asked (grounded Observation -> Question -> Answer). Returns
        the number of entries linked. Idempotent."""
        convos = list(db.execute(
            select(Conversation).where(Conversation.farm_id == farm_id)
            .order_by(Conversation.timestamp)
        ).scalars())
        linked = 0
        for c in convos:
            obs = db.execute(
                select(Observation)
                .where(Observation.farm_id == farm_id, Observation.timestamp <= c.timestamp)
                .order_by(Observation.timestamp.desc()).limit(1)
            ).scalar_one_or_none()
            if obs is None:
                continue
            entry = DatasetRepository.get_by_observation(db, obs.id)
            if entry and entry.conversation_reference != c.id:
                entry.conversation_reference = c.id
                linked += 1
        if linked:
            db.commit()
        return linked
