"""Value types exchanged across the ports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawRecord:
    """Envelope for a raw payload."""

    key: str            # "<entity_type>:<id>"
    entity_type: str
    payload: dict
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class RunResult:
    """Run summary."""

    raw_written: int
    staging_written: int
    api_calls: int
