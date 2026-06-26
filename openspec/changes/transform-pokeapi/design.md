# Design — Transform (staging → analytics star)

Solution reference for the `transform-pokeapi` change. `proposal.md` holds the *what/why*; this records
the *how/why* of the gold model and the algorithm it serves. **Impl is deferred** (the brief asks for
Transform as a plan/diagram) — this is the agreed blueprint, so building it later is mechanical.

## 1. Goal

Remodel `staging` (silver, per-entity faithful projection) into `analytics` (gold, **star schema**)
that serves one flagship consumer — a competitive **team-building optimizer** — and, on the same
tables, a Pokédex dashboard. The star is effectively a **feature store**: every term the optimizer
reads is a conformed column or a bridge join, so the solver needs no other source.

## 2. The consuming algorithm (why the schema looks like this)

A **MILP** (mixed-integer linear program). A binary pick variable `x_p` per candidate pokemon,
`Σ x_p = 6`, solved **lexicographically** (each stage optimizes within the previous stage's optimum):

1. **max-min coverage** — for each of the 18 defending types, take the team's best offensive answer;
   maximize the *worst* of those 18. Guarantees no type the team can't hit.
2. **min duplicate attacking types** — among coverage-ties, prefer offensive-type diversity.
3. **max total firepower** — among those, maximize the summed best-move scores.

Per-move score:

```
S(p, m, t) = power × (accuracy/100)² × STAB × eff(move_type, t) × stat × speedFactor
   STAB        = 1.5 if move_type ∈ p.types else 1.0
   eff         = the 18×18 type-effectiveness multiplier
   stat        = p.attack if move is physical, p.sp_atk if special   (← move.damage_class picks)
   speedFactor = f(p.speed)
```

**Flagship use case:** "optimal type-balanced 6-team, optionally seeded with must-include pokemon."
The variants are the **same star with a different objective/constraints — not different data**:

- *build-around* a chosen pokemon → fix `x_p = 1` for the seed, optimize the other five.
- *counter a known team* → reweight the coverage objective toward the adversary's defensive types.

`generation_id` supports format/dex scoping (a candidate-pool filter). The data layer is
scenario-agnostic; only the program changes.

## 3. The star (`analytics`, gold)

Center fact, **grain = one pokemon**. The three many-to-many relationships are **bridges** (the honest
Kimball name), not facts.

```
fact_pokemon  (grain: one pokemon)
  pokemon_id            PK
  species_id            FK → dim_species
  generation_id             -- degenerate; format/dex filter
  hp attack defense sp_atk sp_def speed   -- measures
  base_stat_total                         -- derived: Σ of the six stats
  height weight                           -- measures (dashboard)

dim_species   species_id PK · name · evolution_chain_id (family key) ·
              evolves_from_species_id NULL · is_legendary · is_mythical · generation_id
dim_type      type_id PK (1..18) · name
dim_move      move_id PK · name · type_id FK → dim_type · power NULL · accuracy NULL ·
              damage_class (physical|special|status) · pp NULL

bridge_pokemon_type          (pokemon_id FK, type_id FK, slot 1|2)   PK(pokemon_id, type_id)
bridge_pokemon_move          (pokemon_id FK, move_id FK)             PK(pokemon_id, move_id)   -- learnset
bridge_type_effectiveness    (attacking_type_id FK, defending_type_id FK, multiplier)
                             PK(attacking_type_id, defending_type_id)  -- 18×18
```

**Modeling note (defensible):** strict Kimball would call pokemon a *dimension* (stats as attributes).
We keep `fact_pokemon` as the center because the optimizer reads its stats as **measures** and every
bridge hangs off it; `is_legendary` lives on `dim_species` (a species property, joined when filtering
candidates).

## 4. Transform logic — every gold table derives from `staging`

| gold table | from staging | rule |
|---|---|---|
| `fact_pokemon` | `pokemon` (+ `species` for the flag) | copy stats; `base_stat_total = Σ6 stats`; `is_legendary` via species join |
| `dim_species` | `pokemon_species` | copy; evolution **family = `evolution_chain_id`** |
| `dim_type` | `type` | copy id + name |
| `dim_move` | `move` | copy power / accuracy / type_id / damage_class |
| `bridge_pokemon_type` | `pokemon.types` | unnest tuple → rows; `slot` = ordinal; slug → `type_id` |
| `bridge_pokemon_move` | `pokemon.moves` | unnest tuple → **distinct** rows; slug → `move_id` |
| `bridge_type_effectiveness` | `type.{double,half,no}_damage_to` | `double→2.0`, `half→0.5`, `no→0.0`, else `1.0`; over all 18×18 pairs |

All derivations are **set-based SQL over `staging`**. `analytics` is rebuildable from `staging` with
zero API calls — no migrations.

## 5. Staging prerequisite — the learnset

`staging.pokemon` keeps `types`/`abilities` but **not `moves`**. The raw pokemon payload *has*
`moves[]` (Extract reads it for reference discovery), but Load drops it — so today there is **no STAB
and no firepower term**, and the optimizer can't run.

**Fix (EL completion, not Transform):** add `staging.pokemon.moves: tuple[str, ...]` — flatten
`moves[].move.name` to **distinct slugs** (drop the `version_group_details` learn-method detail; the
optimizer only needs *can-learn*). Same projection class as `types` — **silver work, no derivation**,
which is exactly what staging's contract ("everything a deferred Transform might need") already
promises. Tracked in `extract-load-pokeapi`; `bridge_pokemon_move` is then a plain unnest of this tuple.

## 6. Stage placement & the medallion rule

`TransformStage` (deferred) drops in as the **third `Stage`** — the `Stage` ABC + `config.stages` seam
is already built (see the EL design). It **reads only `staging`, writes only `analytics`** via the
deferred `StoragePort.execute`/`query`, and shares no in-memory state with other stages. Because
`analytics` is fully rebuildable from `staging`, there are no migrations.

## 7. Out of scope

The optimizer/solver itself (e.g. PuLP/HiGHS), any serving API, and the dashboard. This change is the
**gold model + plan**; `TransformStage` implementation is deferred and gated on remaining time.
