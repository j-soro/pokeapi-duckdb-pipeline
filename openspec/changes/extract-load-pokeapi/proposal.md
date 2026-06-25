## Why

This project is a working example of how to gather and prepare third-party data for downstream
transformation and analysis. We need a runnable, well-structured **Extract & Load (EL)** pipeline
that pulls related entities from a public API and lands them in a queryable local store, ready for a
later Transform step. PokeAPI is a good stand-in for a real client source: no auth, rich and
naturally-related entities, and enough volume to require pagination, retries, and fair-use handling.

The pipeline follows the **medallion** convention (raw → staging → [future] star schema) with a
**capture/interpret separation of concerns** and **per-layer writer ownership** (Extract *captures*
faithful payloads into `raw`; Load *interprets* `raw` → typed `staging`; each medallion layer has
exactly one writer), so each stage is modular, independently testable, and easy to reason about.

This satisfies and exceeds the assignment's EL requirements — a runnable Python script, **four** entity
types (vs. the required two), local storage, and modular design. The Transform step is delivered
separately as a high-level diagram, exactly as the brief specifies.

## What Changes

- Add a runnable Python EL pipeline that extracts **four related entity types** from PokeAPI —
  `pokemon`, `pokemon-species`, `type`, and `move` — and loads them into a local **DuckDB** database.
  Default scope is **Gen 1 (151 pokemon)** + all 18 types + the full move union (**~913 API calls**,
  measured — 592 of them distinct moves, which dominate the budget), configurable to a smaller scope.
- **Extract** *captures*: it fetches the linked resources (the 151 pokemon, then the species + moves
  they reference, plus the 18 types) and writes **faithful payloads** into the **`raw`** (bronze)
  schema — no decode, no reshaping, so it can't fail on a bad field. It streams records (a generator)
  and is resilient (timeouts, retry/backoff, fair-use throttling, HTTP transport cache). The PokeAPI
  navigation (paths, link-following, url→id parsing) is encapsulated entirely in the source adapter.
- **Load** *interprets*: it reads `raw` payloads, **msgspec-decodes/validates/reshapes** them into the
  typed **`staging`** (silver) schema — one table per entity, **no derived fields**. It is the sole
  writer of `staging` (Extract owns `raw`). A ~50 KB payload becomes ~6 validated columns — a lossy,
  validated projection, not a copy. Re-running Load against cached `raw` costs zero API calls.
- **Pipeline orchestration**: a thin stage-runner (`Pipeline([...]).run(ctx)`) wires the streaming
  ingest behind a single, config-driven CLI entrypoint (`uv run pipeline`) with structured logging and
  a selectable scope. A future `TransformStage` (staging → star schema) appends with no change to E/L.
- **Idempotency & resume**: re-runs are safe — `raw` upserts by key (and serves as the checkpoint, so a
  crashed run resumes only the missing entities), `staging` uses `INSERT OR REPLACE` by primary key.
- **Caching (two complementary layers)**: the `raw` (bronze) layer is the cross-run cache — Load/Transform
  re-derive from `raw` with zero API calls. In addition, a **default-on HTTP transport cache (hishel,
  internal to the source adapter)** honors the API's cache headers and protects PokeAPI while iterating
  on the fetch logic — being a polite HTTP citizen, as the API requests.
- Project scaffolding: `uv`-managed dependencies, modular package layout, **unit tests for every
  module** (extract with a fake fetcher, models from JSON fixtures, load against in-memory DuckDB,
  plus idempotency + resume tests), and a README covering how to run it and the approach taken.

## Capabilities

### New Capabilities
- `data-extraction`: PokeAPI *capture* — fetches `pokemon` then their referenced `species`/`move`s
  (plus the 18 `type`s), with retry/backoff, fair-use throttling, and an HTTP transport cache, and
  writes faithful payloads to `raw`. All PokeAPI navigation is encapsulated behind a minimal source port.
- `data-loading`: *interpret* — reads `raw`, msgspec-decodes/validates/reshapes into the typed
  `staging` (silver, no derivations) schema, idempotently and resumably. Sole writer of `staging`.
- `pipeline-orchestration`: A config-driven stage runner and CLI (`uv run pipeline`) that composes the
  ingest, supports running a single stage (e.g. Load-only against existing `raw`), and is built to host
  a future Transform stage.

### Modified Capabilities
<!-- None — greenfield project, no existing specs. -->

## Success Criteria

- `uv run pipeline` produces `data/pokemon.duckdb` with both the `raw` (bronze, written by Extract)
  and `staging` (silver, written by Load) schemas populated for the default scope.
- A second run is **idempotent** (same result) and **resumes** only the missing entities after an interruption.
- `staging` tables are typed with **no derived fields**; `raw` retains the original payloads + `fetched_at`.
- Unit tests pass for every module (extract, models, load), including idempotency + resume tests.
- README explains how to run it and the approach/decisions taken.

## Impact

- **New code**: Python package `pokeapi_pipeline` — flat layout (`config.py`, `ports.py`, `models.py`,
  `source.py`, `storage.py`, `pipeline.py`, `runner.py`, `cli.py`), `pyproject.toml` managed by `uv`, unit tests.
- **Dependencies**: `httpx` (HTTP), `hishel` (HTTP transport cache), `msgspec` (typed decode + TOML config),
  `duckdb` (storage); dev: `pytest`, `ruff`. Config decoded via `msgspec.toml` (stdlib `tomllib`). No auth/secrets.
- **External systems**: PokeAPI (read-only, rate-limited; mitigated by caching + polite throttling).
  Requires a custom `User-Agent` — the default `python-urllib`/`httpx` UA is 403'd by Cloudflare.
- **Outputs**: `data/pokemon.duckdb` with `raw` + `staging` schemas.
- **Not in scope (deferred)**: the Transform step (star schema / derivations like BST and the type
  matrix — planned via diagram for now), the team-builder algorithm, and any serving API.
