"""CLI driving adapter: wire the concrete adapters and run the pipeline."""

import logging
import uuid
from datetime import UTC, datetime

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
        storage = DuckDbStorage(self._config.db_path)
        run_id = uuid.uuid4().hex
        try:
            storage.begin_run(run_id, datetime.now(UTC), self._config.limit, self._config.stages)
            log.info(
                "run %s starting — stages: %s, scope: %d",
                run_id,
                self._config.stages,
                self._config.limit,
            )
            source = PokeApiSource(self._config)
            pipeline = Pipeline(
                [
                    ExtractStage(source, storage, self._config.limit),
                    LoadStage(storage),
                ],
                self._config.stages,
            )
            result = pipeline.run()
            storage.finish_run(
                run_id, datetime.now(UTC), "success", result.raw_written, result.staging_written
            )
            log.info(
                "run %s done — raw: %d, staging: %d",
                run_id,
                result.raw_written,
                result.staging_written,
            )
            return result
        except Exception as exc:
            storage.finish_run(
                run_id, datetime.now(UTC), "failed", error=f"{type(exc).__name__}: {exc}"
            )
            log.error("run %s failed: %s", run_id, exc)
            raise
        finally:
            storage.close()


def main() -> None:
    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(message)s")
    if config.log_level != "DEBUG":
        logging.getLogger("httpx").setLevel(logging.WARNING)  # quiet per-request lines
    runner: PipelineRunnerPort = CLIPipelineRunner(config)
    runner.run()


if __name__ == "__main__":
    main()
