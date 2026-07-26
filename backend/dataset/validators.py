"""Validators — decide whether a NEW dataset entry is good enough to be VALIDATED
(and thus eligible for export). Terminal states (EXPORTED/ARCHIVED) are never
downgraded here.
"""
from backend.dataset.models import DatasetEntry, EXPORTED, ARCHIVED, NEW, VALIDATED

MIN_QUALITY = 50  # a usable training record needs at least this quality


class Validators:
    @staticmethod
    def validate(entry: DatasetEntry) -> str:
        """Return the status the entry should hold. Only NEW entries are (re)graded."""
        if entry.status in (EXPORTED, ARCHIVED):
            return entry.status
        if (entry.observation_id and entry.timestamp is not None
                and entry.quality_score >= MIN_QUALITY):
            return VALIDATED
        return NEW
