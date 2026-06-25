## Why

This project is a working example of how to gather and prepare third-party data for downstream
transformation and analysis. We need a runnable, well-structured **Extract & Load (EL)** pipeline
that pulls related entities from a public API and lands them in a queryable local store, ready for a
later Transform step. PokeAPI is a good stand-in for a real client source: no auth, rich and
naturally-related entities, and enough volume to require pagination, retries, and fair-use handling.

The pipeline follows the **medallion** convention (raw → staging → [future] star schema) and a
**tap/target separation of concerns** (Extract emits records; Load is the sole writer), so each stage
is modular, independently testable, and easy to reason about.

This satisfies and exceeds the assignment's EL requirements — a runnable Python script, **four** entity
types (vs. the required two), local storage, and modular design. The Transform step is delivered
separately as a high-level diagram, exactly as the brief specifies.

## What Changes

- Add a runnable Python EL pipeline that extracts **four related entity types** from PokeAPI —
  `pokemon`, `pokemon-species`, `type`, and `move` — and loads them into a local **DuckDB** database.
  Default scope is **Gen 1 (151 pokemon)** + all 18 types + the full move union (**~913 API calls**,
  measured — 592 of them distinct moves, which dominate the budget), configurable to a smaller scope.
- **Extract** is a *tap*: a generator that crawls PokeAPI (paginated listing + per-entity detail,
  following discovered links for species/moves until the frontier is closed) and **yields raw records**.
  It has **no database dependency** and is resilient (timeouts, retry/backoff, fair-use throttling).
- **Load** is the *sole writer* (*target*): it consumes the record stream, batches it, and writes two
  DuckDB schemas — **`raw`** (bronze: payload + `fetched_at`/source metadata; doubles as the cache /
  replay layer) and **`staging`** (silver: typed, one table per entity, **no derived fields**).
- **Pipeline orchestration**: a thin stage-runner (`Pipeline([...]).run(ctx)`) wires the streaming
  ingest behind a single, config-driven CLI entrypoint (`uv run pipeline`) with structured logging and
  a selectable scope. A future `TransformStage` (staging → star schema) appends with no change to E/L.
- **Idempotency & resume**: re-runs are safe — `raw` upserts by key (and serves as the checkpoint, so a
  crashed run resumes only the missing entities), `staging` uses `INSERT OR REPLACE` by primary key.
- **Caching**: the `raw` (bronze) layer is the primary cache — downstream (Load/Transform) re-derives
  from `raw` with zero API calls. An optional transport-level HTTP cache (internal to Extract) speeds
  up iterating on the crawler itself.
- Project scaffolding: `uv`-managed dependencies, modular package layout, **unit tests for every
  module** (extract with a fake fetcher, models from JSON fixtures, load against in-memory DuckDB,
  plus idempotency + resume tests), and a README covering how to run it and the approach taken.

## Capabilities

### New Capabilities
- `data-extraction`: A DB-agnostic PokeAPI *tap* — paginated, link-following frontier crawl over
  `pokemon`/`species`/`type`/`move`, with retry/backoff, fair-use throttling, and a transport cache,
  that yields raw records.
- `data-loading`: The sole *target* — consumes the record stream and writes the DuckDB `raw` (bronze)
  and `staging` (silver, typed, no derivations) schemas idempotently and resumably.
- `pipeline-orchestration`: A config-driven stage runner and CLI (`uv run pipeline`) that composes the
  ingest, supports running a single stage (e.g. Load-only against existing `raw`), and is built to host
  a future Transform stage.

### Modified Capabilities
<!-- None — greenfield project, no existing specs. -->

## Success Criteria

- `uv run pipeline` produces `data/pokemon.duckdb` where **Load** has written both the `raw`
  (bronze) and `staging` (silver) schemas for the default scope. (Extract only emits records.)
- A second run is **idempotent** (same result) and **resumes** only the missing entities after an interruption.
- `staging` tables are typed with **no derived fields**; `raw` retains the original payloads + `fetched_at`.
- Unit tests pass for every module (extract, models, load), including idempotency + resume tests.
- README explains how to run it and the approach/decisions taken.

## Impact

- **New code**: Python package `pokeapi_pipeline` (`extract/`, `load/`, `models/`, `config`, pipeline + CLI),
  `pyproject.toml` managed by `uv`, unit tests.
- **Dependencies**: `httpx` (HTTP), `msgspec` (typed decode of raw → domain), `duckdb` (storage);
  dev: `pytest`, `ruff`; optional `hishel` (transport cache). Config via stdlib `tomllib`. No auth/secrets.
- **External systems**: PokeAPI (read-only, rate-limited; mitigated by caching + polite throttling).
  Requires a custom `User-Agent` — the default `python-urllib`/`httpx` UA is 403'd by Cloudflare.
- **Outputs**: `data/pokemon.duckdb` with `raw` + `staging` schemas.
- **Not in scope (deferred)**: the Transform step (star schema / derivations like BST and the type
  matrix — planned via diagram for now), the team-builder algorithm, and any serving API.
