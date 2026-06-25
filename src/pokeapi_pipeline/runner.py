"""Composition root: build adapters from config, wire stages, run the pipeline."""

from pokeapi_pipeline.config import Config
from pokeapi_pipeline.pipeline import ExtractStage, LoadStage, Pipeline, Stage
from pokeapi_pipeline.records import RunResult
from pokeapi_pipeline.source import PokeApiSource
from pokeapi_pipeline.storage import DuckDbStorage


class PipelineRunner:
    """Wires the concrete adapters and stages, then runs them (PipelineRunnerPort)."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def run(self) -> RunResult:
        storage = DuckDbStorage(self._config.db_path)
        try:
            source = PokeApiSource(self._config)
            stages: list[Stage] = [
                ExtractStage(source, storage, self._config.limit),
                LoadStage(storage),
            ]
            return Pipeline(stages, self._config.stages).run()
        finally:
            storage.close()
