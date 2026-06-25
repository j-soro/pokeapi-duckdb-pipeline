"""CLI driving adapter: wire the concrete adapters and run the pipeline."""

import logging

from pokeapi_pipeline.adapters.source import PokeApiSource
from pokeapi_pipeline.adapters.storage import DuckDbStorage
from pokeapi_pipeline.config import Config, load_config
from pokeapi_pipeline.core.application.pipeline import ExtractStage, LoadStage, Pipeline
from pokeapi_pipeline.core.application.ports import PipelineRunnerPort
from pokeapi_pipeline.core.domain.records import RunResult

log = logging.getLogger(__name__)


class CLIPipelineRunner:
    """Driving adapter implementing PipelineRunnerPort: wire concretes, run the pipeline."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def run(self) -> RunResult:
        log.info("pipeline starting — stages: %s", self._config.stages)
        storage = DuckDbStorage(self._config.db_path)
        try:
            source = PokeApiSource(self._config)
            pipeline = Pipeline(
                [
                    ExtractStage(source, storage, self._config.limit),
                    LoadStage(storage),
                ],
                self._config.stages,
            )
            result = pipeline.run()
            log.info("done — raw: %d, staging: %d", result.raw_written, result.staging_written)
            return result
        finally:
            storage.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    runner: PipelineRunnerPort = CLIPipelineRunner(load_config())
    runner.run()


if __name__ == "__main__":
    main()
