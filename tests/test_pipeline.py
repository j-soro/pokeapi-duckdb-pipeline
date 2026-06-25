"""Stage and Pipeline tests over the real fixtures, in-memory DuckDB.

FakeSource isolates the stages from the HTTP adapter; every captured record stages
to exactly one row, so staging counts equal the number of raw records.
"""

from collections.abc import Iterator

from pokeapi_pipeline.adapters.storage import DuckDbStorage
from pokeapi_pipeline.core.application.pipeline import ExtractStage, LoadStage, Pipeline
from pokeapi_pipeline.core.domain.records import RawRecord


class FakeSource:
    """SourcePort stub: replays captured records, honoring the resume set."""

    def __init__(self, records: list[RawRecord]) -> None:
        self._records = records

    def records(self, limit: int, existing: set[str]) -> Iterator[RawRecord]:
        return (r for r in self._records if r.key not in existing)


def test_extract_writes_the_captured_universe(
    storage: DuckDbStorage, raw_records: list[RawRecord]
) -> None:
    result = ExtractStage(FakeSource(raw_records), storage, limit=151).run()
    assert result.raw_written == len(raw_records)
    assert storage.existing_raw_keys() == {r.key for r in raw_records}


def test_extract_resumes_skipping_existing(
    storage: DuckDbStorage, raw_records: list[RawRecord]
) -> None:
    storage.write_raw(raw_records[:5])  # already captured
    result = ExtractStage(FakeSource(raw_records), storage, limit=151).run()
    assert result.raw_written == len(raw_records) - 5  # only the missing ones re-fetched


def test_load_stages_every_entity(storage: DuckDbStorage, raw_records: list[RawRecord]) -> None:
    storage.write_raw(raw_records)
    result = LoadStage(storage).run()
    assert result.staging_written == len(raw_records)  # one staging row per raw record


def test_pipeline_runs_only_active_stages(
    storage: DuckDbStorage, raw_records: list[RawRecord]
) -> None:
    storage.write_raw(raw_records)  # raw already populated
    stages = [ExtractStage(FakeSource(raw_records), storage, 151), LoadStage(storage)]
    result = Pipeline(stages, active=("load",)).run()  # extract inactive
    assert result.raw_written == 0  # extract skipped
    assert result.staging_written == len(raw_records)


def test_pipeline_folds_both_stages(storage: DuckDbStorage, raw_records: list[RawRecord]) -> None:
    stages = [ExtractStage(FakeSource(raw_records), storage, 151), LoadStage(storage)]
    result = Pipeline(stages, active=("extract", "load")).run()
    assert result.raw_written == len(raw_records)
    assert result.staging_written == len(raw_records)
