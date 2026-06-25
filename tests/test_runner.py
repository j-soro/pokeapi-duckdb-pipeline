"""PipelineRunner end-to-end: real composition root, offline transport.

The runner builds the real PokeApiSource, so we patch its transport factory to the
fixture-replaying MockTransport — exercising the full extract -> load wiring without network.
"""

from pathlib import Path

import httpx
import pytest

from pokeapi_pipeline.config import Config
from pokeapi_pipeline.runner import PipelineRunner
from pokeapi_pipeline.source import PokeApiSource


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, mock_transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(PokeApiSource, "_default_transport", lambda self: mock_transport)


def test_full_run_extracts_and_loads(
    tmp_path: Path, fixtures: dict[str, dict], full_limit: int
) -> None:
    db = tmp_path / "pokemon.duckdb"
    config = Config(db_path=str(db), limit=full_limit, request_delay=0.0)
    result = PipelineRunner(config).run()
    assert result.raw_written == len(fixtures)  # whole captured universe captured
    assert result.staging_written == len(fixtures)  # and every one staged
    assert db.exists()


def test_load_only_run_skips_extract(
    tmp_path: Path, fixtures: dict[str, dict], full_limit: int
) -> None:
    db = tmp_path / "pokemon.duckdb"
    PipelineRunner(Config(db_path=str(db), limit=full_limit, request_delay=0.0)).run()  # populate
    result = PipelineRunner(
        Config(db_path=str(db), limit=full_limit, request_delay=0.0, stages=("load",))
    ).run()
    assert result.raw_written == 0  # extract not active
    assert result.staging_written == len(fixtures)  # staging rebuilt from existing raw
