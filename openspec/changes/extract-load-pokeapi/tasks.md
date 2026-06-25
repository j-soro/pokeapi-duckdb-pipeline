# Tasks — Extract & Load (PokeAPI → DuckDB)

Build order for the `extract-load-pokeapi` change. Inner-to-outer: contracts and
types first, then adapters, then orchestration, then the CLI, then tests. Each box
is a reviewable step — we go one at a time.

Flat package layout (no per-layer folders):
`config.py · ports.py · models.py · source.py · storage.py · pipeline.py · runner.py · cli.py`

## 1. Contracts & config

- [ ] `ports.py`: `SourcePort` (single `records(scope, have) -> Iterator[RawRecord]`),
      `StoragePort` (`existing_raw_keys`, `write_raw`, `read_raw`, `write_staging`,
      `execute`, `query`), `PipelineRunnerPort` (`run(overrides) -> RunResult`).
- [ ] `ports.py`: `RawRecord` dataclass (`key`, `entity_type`, `payload: dict`, `fetched_at`)
      — the bronze envelope / port currency (not domain).
- [ ] `config.py`: `Config` (frozen msgspec struct: scope, db_path, user_agent, throttle,
      refresh, completeness_gate) + `load_config()` via `msgspec.toml.decode`. CLI overrides merge.
- [ ] `config.toml` at root: default Gen-1 scope (151) + run settings.

## 2. Domain models

- [ ] `models.py`: msgspec structs = staging schema. `Pokemon`, `Species`, `Type`, `Move`
      (`power: int | None`). These are the typed projection Load decodes raw into.

## 3. Source adapter (capture)

- [ ] `source.py`: `PokeApiSource` implements `SourcePort`. Private helpers own ALL PokeAPI
      specifics: base URL, paths, **custom User-Agent** (default UA is 403'd), hishel transport
      cache, `_list_pokemon`, `_list_types`, `_fetch`, `_references` (url→key parsing).
- [ ] `records()`: pass 1 fetch pokemon → extract referenced keys; pass 2 fetch
      species + moves + the fixed 18 types. Skip keys in `have` (resume); pokemon re-traversed
      for discovery are served from hishel cache.

## 4. Storage adapter (interpret + persist)

- [ ] `storage.py`: `DuckDbStorage` implements `StoragePort`. One connection. Ensures schemas
      `raw`, `staging` (+ `meta`) on init.
- [ ] `write_raw`: upsert `RawRecord`s into `raw.*` by key (`INSERT OR REPLACE`), payload as JSON.
- [ ] `read_raw` / `write_staging`: Load reads raw payloads, **msgspec-decodes into `models.py`
      structs** (validate + reshape: url→id, flatten stats, nullable power), writes typed `staging.*`.

## 5. Orchestration

- [ ] `pipeline.py`: `Context` + `Stats` (run-state; no logger). `Pipeline([stages]).run(ctx)`
      dumb runner (skip inactive). `ExtractStage`, `LoadStage`, `TransformStage` (off by default).
- [ ] `runner.py`: `PipelineRunner` (composition root) — build adapters from config, wire stages,
      run `Pipeline`, return `RunResult`. Manual DI, no container.

## 6. CLI & logging

- [ ] `cli.py`: thin driving adapter. Parse args (argparse now; click later) → `RunOverrides`
      → `PipelineRunner(...).run()`. Configure stdlib `logging` once here.

## 7. Tests (per module)

- [ ] Source: fake/mocked HTTP → assert yielded `RawRecord`s, resume skips `have`.
- [ ] Storage/Load: seed `raw` with JSON fixtures → assert typed `staging` rows + msgspec
      validation errors; idempotency (re-run = same state); resume (only missing fetched).
- [ ] In-memory DuckDB; fixtures captured from the validated spike.

## 8. Nice-to-have (observability)

- [ ] `meta.runs` table: `PipelineRunner` writes one row per run from `ctx.stats`
      (run_id, started/finished, scope, api_calls, counts, status). Run lineage/audit.

## 9. Deliverables

- [ ] README: how to run + approach/decisions.
- [ ] Diagrams: high-level architecture/data-flow + Transformation Plan (star schema deferred).
- [ ] Share the repository with reviewers.
