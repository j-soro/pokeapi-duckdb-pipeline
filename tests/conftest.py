"""Shared fixtures: real captured payloads as RawRecords, and an in-memory store."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pokeapi_pipeline.records import RawRecord
from pokeapi_pipeline.storage import DuckDbStorage

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_records() -> list[RawRecord]:
    return [
        RawRecord(
            key=f"{path.parent.name}:{path.stem}",
            entity_type=path.parent.name,
            payload=json.loads(path.read_text()),
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for path in sorted(_FIXTURES.rglob("*.json"))
    ]


@pytest.fixture
def storage() -> Iterator[DuckDbStorage]:
    store = DuckDbStorage(":memory:")
    yield store
    store.close()
