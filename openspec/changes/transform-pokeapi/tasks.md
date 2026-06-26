# Tasks — Transform (staging → analytics star)

**Deferred**: implemented only if time remains after `extract-load-pokeapi` closes. Build order
inner-to-outer, mirroring EL. The diagram (the brief's actual deliverable) is the only must-ship item.

## 1. Prerequisite (EL completion — tracked in extract-load-pokeapi)

- [x] `staging.pokemon.moves`: flatten `moves[].move.name` → distinct slug tuple
      (`models.py`, `mapping.py`, `schema.sql`, a test), mirroring `types`. Enables `bridge_pokemon_move`.

## 2. Deliverable (must ship)

- [x] Transform Plan diagram: the `analytics` star, authored as DDL + Mermaid → exported to
      `diagrams/star-schema.svg`, linked from the README.

## 3. Gold schema (deferred impl)

- [ ] `analytics` DDL: the 7 tables with PK/FK (the diagram's DDL source is the seed).

## 4. Domain (deferred impl)

- [ ] staging→gold reshape/derive fns in `core/domain` (BST sum, the 18×18 effectiveness matrix,
      the three bridge unnests, slug→id resolution).

## 5. TransformStage (deferred impl)

- [ ] `StoragePort.execute`/`query` (the deferred port methods).
- [ ] `TransformStage` (reads `staging`, writes `analytics`); activate via `config.stages`.

## 6. Tests (deferred impl)

- [ ] Per gold table: derivation correctness (BST sum, 18×18 matrix completeness, bridge cardinality),
      rebuildability/idempotency. In-memory DuckDB, reusing the staging fixtures.
