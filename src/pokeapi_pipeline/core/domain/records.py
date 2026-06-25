"""Value types exchanged across the ports."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawRecord:
    """Envelope for a raw payload."""

    key: str  # "<entity_type>:<id>"
    entity_type: str
    payload: dict
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class RunResult:
    """Run summary; stages return partial results the pipeline folds together."""

    raw_written: int = 0
    staging_written: int = 0

    @classmethod
    def merge(cls, results: Iterable["RunResult"]) -> "RunResult":
        items = list(results)
        return cls(
            raw_written=sum(r.raw_written for r in items),
            staging_written=sum(r.staging_written for r in items),
        )
