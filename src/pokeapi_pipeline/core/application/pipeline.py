"""Pipeline stages and the dumb runner that selects and folds them.

Stages share nothing in memory: each reads and writes the DuckDB layers and
reports only what it wrote. Transform drops in later as a third Stage.
"""

import logging
from abc import ABC, abstractmethod

from pokeapi_pipeline.core.application.ports import SourcePort, StoragePort
from pokeapi_pipeline.core.domain.mapping import ENTITY_TYPES, to_staging
from pokeapi_pipeline.core.domain.records import RunResult

log = logging.getLogger(__name__)


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
        counts: dict[str, int] = {}
        for entity in ENTITY_TYPES:
            rows = [to_staging(entity, payload) for payload in self._storage.read_raw(entity)]
            counts[entity] = self._storage.write_staging(entity, rows)
        total = sum(counts.values())
        log.info("staged %d rows (%s)", total, ", ".join(f"{e}={n}" for e, n in counts.items()))
        return RunResult(staging_written=total)


class Pipeline:
    """Runs the active stages in order and folds their results."""

    def __init__(self, stages: list[Stage], active: tuple[str, ...]) -> None:
        self._stages = stages
        self._active = active

    def run(self) -> RunResult:
        results: list[RunResult] = []
        for stage in self._stages:
            if stage.name not in self._active:
                continue
            log.info(">> %s", stage.name)
            results.append(stage.run())
        return RunResult.merge(results)
