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
│     models.py  (Pokemon · Species · Type · Move — msgspec Structs = staging)   │
│     (RawRecord lives in ports.py — generic envelope, not domain; PokeAPI       │
│      link/url navigation is private to the source adapter)                     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Ports

```python
class SourcePort(Protocol):                    # PokeAPI — minimal; adapter hides ALL navigation
    def records(self, scope: Scope, have: set[str]) -> Iterator[RawRecord]: ...
    # RawRecord (key, entity_type, payload: dict, fetched_at) is defined here in ports.py

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
(config, stats, active stages) — **never data, and no logger** (logging is stdlib module loggers,
configured once in `cli.py`).

```python
class Pipeline:
    def run(self, ctx: Context) -> None:
        for stage in self._stages:
            if stage.name in ctx.active:        # transform omitted by default → skipped
                log.info("▶ %s", stage.name)    # module logger; Context holds no logger
                stage.run(ctx)
```

- **ExtractStage** — *capture*. `source.records(scope, have)` is the generator yielding `RawRecord`s;
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

## 5. Extraction — linked-resource fetch (inside the source adapter)

The link graph is shallow and known (pokemon → {species, moves}; types independent), so there is **no
generic frontier/worklist** — just two explicit passes inside `PokeApiSource.records()`:
1. List the pokemon in scope (paginate `/pokemon`, cap 151) and fetch each; collect the referenced
   species + move keys from `species.url` / `moves[].move.url`.
2. Fetch those species + moves, plus the fixed 18 types.

Moves are the only entity not enumerable up front (there is no "moves of Gen 1" endpoint) — the sole
reason link-following exists. URL→id (`…/(\d+)/?$`) and all path/navigation logic are **private to the
adapter**, not domain. **Resume** skips keys already in `raw` (the `have` set); re-traversed pokemon are
served from the hishel cache. Custom **`User-Agent` required** (default UA is 403'd by Cloudflare).
Polite throttle between calls.

## 6. Config, caching, idempotency

- **Config**: `config.toml` at root → `msgspec.toml.decode` into a `frozen Config` struct (zero extra
  deps on 3.13). CLI flags override. **Manual DI** in `PipelineRunner` (no container).
- **Cache (two layers)**: `raw` is the cross-run cache — re-run Load/Transform with zero API calls.
  Plus a **default-on hishel HTTP transport cache** inside the source adapter (honors API cache headers;
  polite while iterating on the fetch logic).
- **Idempotency/resume**: `write_raw` upsert by key; `staging` `INSERT OR REPLACE` by PK; resume via
  `existing_raw_keys()`. Knobs: `--refresh` (force re-pull) and a **completeness gate** (Load warns/refuses
  on an incomplete `raw`).

## 7. Module layout (src-layout)

```
config.toml   pyproject.toml   README.md
src/pokeapi_pipeline/                            # FLAT — no per-layer folders
  config.py      # Config + load_config()
  ports.py       # SourcePort · StoragePort · PipelineRunnerPort · RawRecord
  models.py      # Pokemon · Species · Type · Move (msgspec structs = staging schema)
  source.py      # PokeApiSource — SourcePort adapter (httpx + hishel + UA; navigation private)
  storage.py     # DuckDbStorage — StoragePort adapter + msgspec decode (raw → staging)
  pipeline.py    # Context · Stats · Pipeline · ExtractStage · LoadStage · TransformStage
  runner.py      # PipelineRunner — composition root (manual DI)
  cli.py         # thin driving adapter (argparse → runner); configures logging
tests/           # fake SourcePort; in-memory DuckDB; JSON fixtures
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
