"""CLIPipelineRunner end-to-end: real driving adapter, offline transport.

The adapter wires the real PokeApiSource, so we patch its transport factory to the
fixture-replaying MockTransport — exercising the full extract -> load wiring without network.
"""

from pathlib import Path

import httpx
import pytest

from pokeapi_pipeline.adapters.cli import CLIPipelineRunner, main
from pokeapi_pipeline.adapters.source import PokeApiSource
from pokeapi_pipeline.config import Config


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, mock_transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(PokeApiSource, "_default_transport", lambda self: mock_transport)


def test_full_run_extracts_and_loads(
    tmp_path: Path, fixtures: dict[str, dict], full_limit: int
) -> None:
    db = tmp_path / "pokemon.duckdb"
    config = Config(db_path=str(db), limit=full_limit, request_delay=0.0)
    result = CLIPipelineRunner(config).run()
    assert result.raw_written == len(fixtures)  # whole captured universe captured
    assert result.staging_written == len(fixtures)  # and every one staged
    assert db.exists()


def test_load_only_run_skips_extract(
    tmp_path: Path, fixtures: dict[str, dict], full_limit: int
) -> None:
    db = tmp_path / "pokemon.duckdb"
    CLIPipelineRunner(
        Config(db_path=str(db), limit=full_limit, request_delay=0.0)
    ).run()  # populate
    result = CLIPipelineRunner(
        Config(db_path=str(db), limit=full_limit, request_delay=0.0, stages=("load",))
    ).run()
    assert result.raw_written == 0  # extract not active
    assert result.staging_written == len(fixtures)  # staging rebuilt from existing raw


def test_main_loads_config_and_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixtures: dict[str, dict], full_limit: int
) -> None:
    db = tmp_path / "pokemon.duckdb"
    config = Config(db_path=str(db), limit=full_limit, request_delay=0.0)
    monkeypatch.setattr("pokeapi_pipeline.adapters.cli.load_config", lambda: config)
    main()  # configures logging, loads config, runs the pipeline
    assert db.exists()
