## Why

Staging (silver) is a faithful, per-entity projection of PokeAPI — not a consumption-ready model.
Downstream business consumers need an **`analytics` (gold)** layer that remodels staging into a
**star schema** where every metric and relationship is precomputed and conformed. The flagship
consumer is a **competitive team-building optimizer**: a solver that picks an optimal 6-pokemon team
by type coverage and firepower. The same star also backs a plain Pokédex dashboard — one gold model,
two readers.

Per the brief, **Transform is delivered as a plan + diagram, not code**. This change records that
plan: the gold star schema, the algorithm it feeds, and the staging-to-gold derivation for every
table (proving the data is already captured). The `TransformStage` implementation is deferred.

## What Changes

- Define the `analytics` (gold) **star schema**: `fact_pokemon` (grain = one pokemon) + conformed
  dimensions `dim_species` / `dim_type` / `dim_move` + bridges `bridge_pokemon_type` /
  `bridge_pokemon_move` / `bridge_type_effectiveness` (the 18×18 matrix).
- Document the **consuming algorithm**: a lexicographic MILP (max-min type coverage → minimize
  duplicate attacking types → maximize firepower) and how each program term maps to a star column.
- Map **every gold table to its staging derivation** — the Transform logic — so it is provable that
  no field the optimizer needs is missing.
- Ship the **diagram** (DDL source → SVG, exported from the IDE) under `diagrams/`, linked from the README.
- *(Deferred impl)* `TransformStage` reads `staging`, writes `analytics` via `StoragePort.execute`.

## Capabilities

### New Capabilities
- `data-transformation`: remodel `staging` (silver) into the `analytics` (gold) star schema that
  serves the team-optimizer and the Pokédex dashboard. Reads only `staging`, writes only `analytics`;
  fully rebuildable (no migrations). Plan + diagram now; `TransformStage` impl deferred.

### Modified Capabilities
<!-- None as its own delta. Dependency below is delivered by the extract-load-pokeapi change. -->

### Dependency
- Requires `staging.pokemon` to carry the **learnset** (`moves`). The raw payload already has it
  (`moves[]`, used by Extract for reference discovery); Load currently drops it. Adding it is a
  faithful projection (flatten to a distinct slug tuple, like `types`) — **silver work, no
  derivation** — and completes staging's stated contract ("everything a deferred Transform might
  need"). Delivered by completing `extract-load-pokeapi`. See design §5.

## Success Criteria

- The star schema is fully specified (tables, grains, PK/FK, measures) and rendered as a diagram
  linked from the README.
- Every gold table has a documented derivation from `staging` — no optimizer input is missing.
- The MILP use case is described well enough to implement directly against the star, with no
  re-extraction.
- Transform reads only `staging` and writes only `analytics`; `analytics` is rebuildable from `staging`.

## Alternatives considered

- **dbt for the gold layer.** dbt is the standard tool here and what a production warehouse would use
  (model per table, built-in `relationships` / `accepted_values` tests, lineage for free). For seven
  tables built once it's overhead, and it runs outside the `StoragePort` seam — so the plan keeps the
  derivations as in-stage SQL and treats dbt as the scale-up path, not the default.

## Impact

- **New artifacts**: `diagrams/star-schema.*` (DDL + Mermaid source + exported SVG); this change's design.
- **Dependency (EL completion)**: `staging.pokemon.moves` — `models.py`, `mapping.py`, `schema.sql`,
  a test — tracked in `extract-load-pokeapi`.
- **Deferred**: `TransformStage` impl (`StoragePort.execute`/`query`, the gold SQL), the optimizer
  solver itself, any serving API/dashboard.
- **External systems**: none — gold is pure SQL over `staging`.
