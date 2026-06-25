"""Pipeline stages and the dumb runner that selects and folds them.

Stages share nothing in memory: each reads and writes the DuckDB layers and
reports only what it wrote. Transform drops in later as a third Stage.
"""

from abc import ABC, abstractmethod

from pokeapi_pipeline.ports import SourcePort, StoragePort
from pokeapi_pipeline.records import RunResult
from pokeapi_pipeline.storage import ENTITY_TYPES, to_staging


class Stage(ABC):
    """One pipeline step; reports what it wrote."""

    name: str

    @abstractmethod
    def run(self) -> RunResult: ...


class ExtractStage(Stage):
    """Capture raw payloads into bronze, skipping keys already stored (resume)."""

    name = "extract"

    def __init__(self, source: SourcePort, storage: StoragePort, limit: int) -> None:
        self._source = source
        self._storage = storage
        self._limit = limit

    def run(self) -> RunResult:
        existing = self._storage.existing_raw_keys()
        written = self._storage.write_raw(self._source.records(self._limit, existing))
        return RunResult(raw_written=written)


class LoadStage(Stage):
    """Interpret each raw payload into typed, validated staging rows."""

    name = "load"

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    def run(self) -> RunResult:
        written = 0
        for entity in ENTITY_TYPES:
            rows = [to_staging(entity, payload) for payload in self._storage.read_raw(entity)]
            written += self._storage.write_staging(entity, rows)
        return RunResult(staging_written=written)


class Pipeline:
    """Runs the active stages in order and folds their results."""

    def __init__(self, stages: list[Stage], active: tuple[str, ...]) -> None:
        self._stages = stages
        self._active = active

    def run(self) -> RunResult:
        return RunResult.merge(s.run() for s in self._stages if s.name in self._active)
