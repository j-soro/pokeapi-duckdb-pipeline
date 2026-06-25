# Design — Extract & Load (PokeAPI → DuckDB)

This is the solution reference for the `extract-load-pokeapi` change. It records the **how** and,
crucially, the **why** behind each decision, so every choice is defensible. `proposal.md` holds the
*what/why*; `RESEARCH.md` (repo root) is the exploration log; this is the agreed blueprint.

## 1. Goals & constraints

- Runnable Python **Extract & Load** pipeline pulling **4 related entity types** from PokeAPI
  (`pokemon`, `pokemon-species`, `type`, `move`) into **one local DuckDB file**.
- Well-structured, modular, **config-driven**, **unit-tested per module**, easily runnable.
- **Transform is diagram-only / deferred** — the architecture leaves a clean seam for it.
- Default scope: **Gen 1 (151 pokemon)** + all 18 types + the full move union (**~913 API calls**,
  measured — 592 distinct moves dominate), configurable to a smaller scope.

## 2. Architecture — hexagonal (ports & adapters)

Two external systems (PokeAPI, DuckDB) → **two driven ports**; one **driving port**. Port count
follows *external systems*, not use-cases (ISP-style segregation was deliberately rejected as ceremony
for a project this size).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  COMPOSITION ROOT / APP ENTRY     PipelineRunner  (implements PipelineRunnerPort)
│  loads config, opens the connection, wires adapters→stages, runs the Pipeline  │
└───────────────┬───────────────────────────────────────────────────────────────┘
                │ instantiates ↓
┌───────────────▼───────────────────────────────────────────────────────────────┐
│  INFRASTRUCTURE / ADAPTERS  (the "how")                                        │
│     PokeApiSource (httpx)                 DuckDbStorage (duckdb)                │
│        implements│ SourcePort                 implements│ StoragePort           │
└──────────────────┼─────────────────────────────────────┼───────────────────────┘
                   │            dependencies point inward ↓
┌──────────────────┼─────────────────────────────────────┼───────────────────────┐
│  APPLICATION  (use cases / orchestration)                                       │
│     Pipeline([ ExtractStage, LoadStage, TransformStage ]).run(ctx)             │
│        ExtractStage ─uses▶ SourcePort + StoragePort.write_raw                   │
│        LoadStage    ─uses▶ StoragePort.read_raw / write_staging                 │
│        TransformStage ─uses▶ StoragePort.execute   (deferred, off by default)   │
│     ── PORTS declared here: SourcePort · StoragePort · PipelineRunnerPort ──    │
└───────────────┬────────────────────────────────────────────────────────────────┘
                │ uses ↓
┌───────────────▼────────────────────────────────────────────────────────────────┐
│  DOMAIN  (pure, no I/O — innermost)                                            │
│     models.py  (Pokemon · Species · Type · Move — msgspec Structs)             │
│     records.py (RawRecord — the bronze envelope)                               │
│     crawl.py   (frontier logic: worklist, dedupe, link-following)              │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Ports

```python
class SourcePort(Protocol):                    # PokeAPI
    def get(self, path: str) -> dict: ...

class StoragePort(Protocol):                   # DuckDB — the whole warehouse, one port/adapter/connection
    def existing_raw_keys(self) -> set[str]: ...                  # resume
    def write_raw(self, records: Iterable[RawRecord]) -> int: ... # bronze, upsert by key
    def read_raw(self, entity_type: str) -> Iterator[dict]: ...   # payloads to decode
    def write_staging(self, entity_type: str, rows: Iterable[Struct]) -> int: ...
    def execute(self, sql: str, params: tuple = ()) -> None: ...  # gold/transform (deferred)
    def query(self, sql: str, params: tuple = ()) -> list[tuple]: ...

class PipelineRunnerPort(Protocol):            # driving — the entry the CLI (or any driver) calls
    def run(self, overrides: RunOverrides) -> RunResult: ...
```

**Rule that keeps `StoragePort` from becoming a junk-drawer:** the port only *moves* data; all *logic*
lives in the stages. Load owns the msgspec decode/validate/reshape; Transform owns its SQL strings.
The adapter must not hide ETL logic.

## 3. The pipeline & stages

`Pipeline` is dumb: it runs stages in order, skipping inactive ones. **Stages communicate only through
the DuckDB medallion layers** (`raw → staging → marts`). `Context` carries cross-cutting run state
(config, logger, stats) — **never data**.

```python
class Pipeline:
    def run(self, ctx: Context) -> None:
        for stage in self._stages:
            if stage.name in ctx.active:        # transform omitted by default → skipped
                ctx.log.info("▶ %s", stage.name)
                stage.run(ctx)
```

- **ExtractStage** — *capture*. `crawl(source)` is a generator yielding `RawRecord`s over the frontier;
  `StoragePort.write_raw` consumes the stream in batches (incremental bronze checkpoint).
  Generators live **only here**.
- **LoadStage** — *interpret*. `read_raw(entity)` → **msgspec decode/validate** → typed `staging` rows
  via `write_staging`. Set-based; no generators.
- **TransformStage** — deferred. Reads `staging`, writes `marts` via `execute(sql)`. Off by default.

### Why Extract ≠ Load (capture vs interpret)

Extract stores faithful payloads and rarely changes; Load parses/validates/shapes and changes often.
Keeping `raw` immutable means a schema or parsing change re-runs **Load against cached raw with zero
API calls**, and Extract can't fail on a validation bug (it just captures bytes). A single
`/pokemon/{id}` payload is ~50KB / 100+ fields; `staging.pokemon` keeps ~6 — Load is a **lossy,
validated projection**, not a copy.

## 4. Data model (medallion, one DuckDB file)

- **`raw.*` (bronze)** — `(key VARCHAR PRIMARY KEY, payload JSON, fetched_at TIMESTAMP)`, upsert by key.
  Doubles as cache + resume checkpoint.
- **`staging.*` (silver)** — typed, one table per entity, **no derived fields**. Confirmed shapes:
  - `pokemon(id PK, name, height, weight, types VARCHAR[], stat columns…, species_id)`
  - `pokemon_species(id PK, name, evolves_from_id INT NULL, generation_id, is_legendary, is_mythical)`
  - `type(id PK, name, damage_relations JSON)` (relations kept structured; matrix is Transform)
  - `move(id PK, name, power INTEGER **NULL**, type_id, damage_class)` — `power` is null for status moves
- **`marts.*` (gold)** — deferred (BST, 18×18 type matrix, evolution families). Diagram only.

## 5. Extraction — frontier crawl

Seed the worklist by paginating `/pokemon` (cap to scope, default 151). For each fetched entity, follow
discovered links (`species.url`, `moves[].move.url`, `types[].type.url`) onto the worklist; dedupe by
key; stop when the frontier is empty. URL→id via `…/(\d+)/?$`. **Resume** skips keys already in
`raw`. Custom **`User-Agent` required** (default httpx/urllib UA is 403'd by Cloudflare). Polite
throttle between calls.

## 6. Config, caching, idempotency

- **Config**: `config.toml` at root → `msgspec.toml.decode` into a `frozen Config` struct (zero extra
  deps on 3.13). CLI flags override. **Manual DI** in `PipelineRunner` (no container).
- **Cache**: `raw` is the cache — re-run Load/Transform with zero API calls. (`hishel` optional, dev only.)
- **Idempotency/resume**: `write_raw` upsert by key; `staging` `INSERT OR REPLACE` by PK; resume via
  `existing_raw_keys()`. Knobs: `--refresh` (force re-pull) and a **completeness gate** (Load warns/refuses
  on an incomplete `raw`).

## 7. Module layout (src-layout)

```
config.toml                         pyproject.toml (uv)
src/pokeapi_pipeline/
  domain/   models.py  records.py  crawl.py      # pure, no I/O
  ports.py
  extract/  pokeapi_source.py                    # SourcePort adapter
  load/     duckdb_storage.py                     # StoragePort adapter + decode usage
  transform/                                      # deferred
  app/      pipeline.py  runner.py  context.py    # PipelineRunner = entry + composition root
  config.py  cli.py                               # cli.py = thin UI driving adapter
tests/                                            # fake SourcePort; in-memory DuckDB; fixtures
```

## 8. Testing

- **Extract**: fake `SourcePort` (fixtures) → assert `raw` rows, dedupe, resume (skip existing keys).
- **Load**: seed `raw` with fixture payloads → assert typed `staging` rows + msgspec validation errors.
- **Idempotency/resume**: re-run yields identical state; interrupted run resumes only missing entities.
- In-memory DuckDB; JSON fixtures captured from the validated spike.

## 9. Status of pre-implementation validation

- **DuckDB** (v1.5.4): array columns + PK + `INSERT OR REPLACE` idempotency, JSON column + `executemany`
  + `json_extract_string` — **PASSED**.
- **PokeAPI**: four endpoint shapes + URL→id parsing + nullable `move.power` — **PASSED** (real-shell run).
- Scope **measured**: 913 API calls / 592 distinct moves.
