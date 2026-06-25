# Tasks — Extract & Load (PokeAPI → DuckDB)

Build order for the `extract-load-pokeapi` change. Inner-to-outer: contracts and
types first, then adapters, then orchestration, then the CLI, then tests. Each box
is a reviewable step — we go one at a time.

Flat package layout (no per-layer folders):
`config.py · ports.py · records.py · models.py · source.py · storage.py · pipeline.py · runner.py · cli.py`

Dev tooling: `uv` (deps/lock), `mise` (python 3.13 + uv), `ruff` (lint + format),
`mypy` (dev-only, lenient), `pytest`.

## 1. Contracts & config

- [x] `ports.py`: `SourcePort` (single `records(limit, have) -> Iterator[RawRecord]`),
      `StoragePort` (`existing_raw_keys`, `write_raw`, `read_raw`, `write_staging`;
      `execute`/`query` deferred with Transform), `PipelineRunnerPort` (`run() -> RunResult`).
- [x] `records.py`: `RawRecord` dataclass (`key`, `entity_type`, `payload: dict`, `fetched_at`)
      + `RunResult` — generic value types crossing the ports (not domain, not `ports.py`).
- [x] `config.py`: `Config` (frozen msgspec struct: `db_path`, `limit`, `user_agent`,
      `request_delay`, `stages`) + `load_config()` via `msgspec.toml.decode`.
      Config-only — no CLI args.
- [x] `config.toml` at root: default Gen-1 scope (151) + run settings.

## 2. Domain models

- [x] `models.py`: msgspec structs = staging schema. `Pokemon`, `Species`, `Type`, `Move` —
      comprehensive analytically-useful field sets (everything a deferred Transform might need,
      no derivations). The typed projection Load decodes/reshapes raw into.

## 3. Source adapter (capture)

- [x] `source.py`: `PokeApiSource` implements `SourcePort`. Private helpers own ALL PokeAPI
      specifics: base URL, paths, **custom User-Agent** (default UA is 403'd), hishel transport
      cache (store-and-use), `_list_pokemon`, `_type_keys`, `_get` (retry/backoff), `_references`
      and `_key` (url→key parsing).
- [x] `records()`: pass 1 fetch pokemon → extract referenced keys; pass 2 fetch
      species + moves + the fixed 18 types. Skip keys in `existing` (resume); pokemon re-traversed
      for discovery are served from the hishel cache.

## 4. Storage adapter (interpret + persist)

- [x] `storage.py`: `DuckDbStorage` implements `StoragePort`. One connection. Ensures `raw` +
      `staging` schemas on init from explicit `schema.sql` (no migrations — staging is rebuildable;
      `meta` deferred to §8).
- [x] `write_raw`: upsert `RawRecord`s into single `raw.records` by key (`ON CONFLICT DO UPDATE`),
      payload as JSON.
- [x] `read_raw` / `write_staging`: Load reads raw payloads → module-level reshape fns (url→id,
      flatten stats, slug tuples, nullable fields) → `to_staging()` ends in `msgspec.convert`
      (the validation gate) → `INSERT OR REPLACE` into typed `staging.*`.

## 5. Orchestration

- [x] `pipeline.py`: `Stage` (ABC) + `ExtractStage`, `LoadStage`. `Pipeline(stages, active)` dumb
      runner — runs active stages, folds each stage's `RunResult`. No shared `Context`: stages get
      deps at construction and communicate only through the DuckDB layers. Transform drops in later
      as a third `Stage` (the seam is the ABC + `config.stages`).
- [x] `runner.py`: `PipelineRunner` (composition root) — build adapters from config, wire stages,
      run `Pipeline`, return `RunResult`. Manual DI, no container.

## 6. CLI & logging

- [ ] `cli.py`: thin driving adapter. `load_config()` → `PipelineRunner(...).run()` — no args,
      fully config-driven. Configure stdlib `logging` once here.

## 7. Tests (per module)

- [x] Source: real captured fixtures replayed via `httpx.MockTransport` → assert the source yields
      exactly the captured universe (completeness oracle), all 4 entity types, resume skips
      `existing` while keeping discovery, url→key parsing, retry/backoff.
- [x] Storage/Load: seed `raw` with the real fixtures → assert typed `staging` rows + msgspec
      validation errors (wrong type, missing required); idempotency (re-run = same state);
      resume (`existing_raw_keys` reflects only stored); every entity reshapes to staging.
- [x] In-memory DuckDB; reuses `tests/fixtures/*` via shared `conftest.py`.

## 8. Nice-to-have (observability)

- [ ] `meta.runs` table: `PipelineRunner` writes one row per run
      (run_id, started/finished, scope, counts, status). Run lineage/audit.

## 9. Deliverables

- [ ] README: how to run + approach/decisions.
- [ ] Diagrams: high-level architecture/data-flow + Transformation Plan (star schema deferred).
- [ ] Share the repository with reviewers.
