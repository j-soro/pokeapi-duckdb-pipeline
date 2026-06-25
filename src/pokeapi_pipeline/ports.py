"""Port contracts (Protocols implemented by adapters)."""

from collections.abc import Iterable, Iterator
from typing import Protocol

from pokeapi_pipeline.records import RawRecord, RunResult


class SourcePort(Protocol):
    """PokeAPI source; the adapter hides navigation."""

    def records(self, limit: int, existing: set[str]) -> Iterator[RawRecord]: ...


class StoragePort(Protocol):
    """DuckDB warehouse: raw and staging."""

    def existing_raw_keys(self) -> set[str]: ...
    def write_raw(self, records: Iterable[RawRecord]) -> int: ...
    def read_raw(self, entity_type: str) -> Iterator[dict]: ...
    def write_staging(self, entity_type: str, rows: Iterable[object]) -> int: ...


class PipelineRunnerPort(Protocol):
    """Driving port invoked by the CLI."""

    def run(self) -> RunResult: ...
