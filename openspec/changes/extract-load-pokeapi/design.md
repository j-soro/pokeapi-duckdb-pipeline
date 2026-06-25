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
│     Pipeline([ ExtractStage, LoadStage, (TransformStage) ], active).run()       │
│        ExtractStage ─uses▶ SourcePort + StoragePort.write_raw                   │
│        LoadStage    ─uses▶ StoragePort.read_raw / write_staging                 │
│        TransformStage ─uses▶ StoragePort.execute   (deferred, off by default)   │
│     ── PORTS declared here: SourcePort · StoragePort · PipelineRunnerPort ──    │
└───────────────┬────────────────────────────────────────────────────────────────┘
                │ uses ↓
┌───────────────▼────────────────────────────────────────────────────────────────┐
│  DOMAIN  (pure, no I/O — innermost)                                            │
│     models.py  (Pokemon · Species · Type · Move — msgspec Structs = staging)   │
│     (RawRecord/RunResult live in records.py — generic value types, not domain; │
│      PokeAPI link/url navigation is private to the source adapter)             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Ports

```python
class SourcePort(Protocol):                    # PokeAPI — minimal; adapter hides ALL navigation
    def records(self, limit: int, have: set[str]) -> Iterator[RawRecord]: ...
    # RawRecord/RunResult are value types defined in records.py (not ports.py, not domain)

class StoragePort(Protocol):                   # DuckDB — the whole warehouse, one port/adapter/connection
    def existing_raw_keys(self) -> set[str]: ...                   # resume
    def write_raw(self, records: Iterable[RawRecord]) -> int: ...  # bronze, upsert by key
    def read_raw(self, entity_type: str) -> Iterator[dict]: ...    # payloads to decode
    def write_staging(self, entity_type: str, rows: Iterable[object]) -> int: ...  # msgspec Structs
    # execute()/query() for gold/transform are deferred — added with TransformStage

class PipelineRunnerPort(Protocol):            # driving — the entry the CLI (or any driver) calls
    def run(self) -> RunResult: ...            # no args — fully config-driven
```

**Rule that keeps `StoragePort` from becoming a junk-drawer:** the port only *moves* data; all *logic*
lives in the stages. Load owns the msgspec decode/validate/reshape; Transform owns its SQL strings.
The adapter must not hide ETL logic.

## 3. The pipeline & stages

`Pipeline` is dumb: it runs the active stages in order and folds each stage's `RunResult` into the run
summary. **Stages communicate only through the DuckDB medallion layers** (`raw → staging → marts`),
never in memory — so there is **no shared `Context`**. Each stage gets its adapters at construction
(manual DI in the runner) and returns only what it wrote; `Stage` is an internal ABC the three stages
inherit. Logging is stdlib module loggers, configured once in `cli.py`.

```python
class Pipeline:
    def run(self) -> RunResult:                 # transform omitted from `active` → skipped
        return RunResult.merge(s.run() for s in self._stages if s.name in self._active)
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
`/pokemon/{id}` payload is ~50KB / 100+ fields; `staging.pokemon` keeps the analytically-useful subset
(stats, types, abilities, sprites, links) — Load is a **validated projection** (flattened, url→id),
not a verbatim copy. Staging carries every source field the deferred Transform might need, not just
basics, so Transform never re-extracts; only true derivations (BST, the type matrix) are left to it.

## 4. Data model (medallion, one DuckDB file)

- **`raw.*` (bronze)** — `(key VARCHAR PRIMARY KEY, payload JSON, fetched_at TIMESTAMP)`, upsert by key.
  Doubles as cache + resume checkpoint.
- **`staging.*` (silver)** — typed, one table per entity. Carries the analytically-useful source
  fields (everything a deferred Transform might need, not just basics); **no derived fields**
  (aggregates/matrices belong to Transform). Slugs are the API's hyphenated `name`s; ids are parsed
  from URLs. Shapes:
  - `pokemon(id PK, name, height, weight, base_experience NULL, "order", is_default, species_id,
    types VARCHAR[], abilities VARCHAR[], sprite_front_default NULL, sprite_back_default NULL,
    hp, attack, defense, special_attack, special_defense, speed)`
  - `pokemon_species(id PK, name, "order", generation_id, evolution_chain_id, evolves_from_id NULL,
    is_legendary, is_mythical, is_baby, capture_rate, base_happiness NULL, gender_rate,
    hatch_counter NULL, has_gender_differences, forms_switchable, growth_rate, color, shape NULL,
    habitat NULL, egg_groups VARCHAR[], flavor_text NULL)` — flavor = English entry, whitespace-cleaned
  - `type(id PK, name, generation_id, move_damage_class NULL,
    {double,half,no}_damage_{to,from} VARCHAR[])` — relations kept as slug lists; the 18×18 matrix is Transform
  - `move(id PK, name, power INTEGER NULL, accuracy NULL, pp NULL, priority, effect_chance NULL,
    type_id, damage_class, target, generation_id)` — `power`/`accuracy` null for status moves
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
  deps on 3.13). **Config-only — no CLI args** (the CLI just loads config and runs). **Manual DI** in
  `PipelineRunner` (no container).
- **Cache (two layers)**: `raw` is the cross-run cache — re-run Load/Transform with zero API calls.
  Plus a **default-on hishel HTTP transport cache** inside the source adapter (honors API cache headers;
  polite while iterating on the fetch logic).
- **Idempotency/resume**: `write_raw` upsert by key; `staging` `INSERT OR REPLACE` by PK; resume via
  `existing_raw_keys()`. A full refresh is a clean rebuild (delete the DuckDB file) — consistent with
  the no-migrations model, so no `force_refresh` knob.

## 7. Module layout (src-layout)

```
config.toml   pyproject.toml   README.md
src/pokeapi_pipeline/                            # FLAT — no per-layer folders
  config.py      # Config + load_config()
  ports.py       # SourcePort · StoragePort · PipelineRunnerPort (pure Protocols)
  records.py     # RawRecord · RunResult (value types crossing the ports)
  models.py      # Pokemon · Species · Type · Move (msgspec structs = staging schema)
  source.py      # PokeApiSource — SourcePort adapter (httpx + hishel + UA; navigation private)
  storage.py     # DuckDbStorage — StoragePort adapter + msgspec decode (raw → staging)
  pipeline.py    # Stage (ABC) · Pipeline · ExtractStage · LoadStage · (TransformStage later)
  runner.py      # PipelineRunner — composition root (manual DI)
  cli.py         # thin driving adapter (loads config → runner); configures logging
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
