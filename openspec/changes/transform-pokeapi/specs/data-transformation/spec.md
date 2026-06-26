## ADDED Requirements

### Requirement: Gold star schema
The analytics layer SHALL model staging as a star — a `fact_pokemon` grain of one pokemon, conformed
dimensions (species, type, move), and bridges for the pokemon↔type, pokemon↔move (learnset), and
18×18 type-effectiveness relationships.

#### Scenario: Fact grain
- WHEN `fact_pokemon` is built
- THEN it holds one row per pokemon with stat measures and `base_stat_total`, keyed to `dim_species`

#### Scenario: Type-effectiveness matrix
- WHEN `bridge_type_effectiveness` is built from staging type damage relations
- THEN it holds one multiplier per (attacking_type, defending_type) across all 18×18 pairs

#### Scenario: Learnset bridge
- WHEN `bridge_pokemon_move` is built
- THEN it holds one row per (pokemon, learnable move), resolved to ids

### Requirement: Derivable from staging only
Every analytics table SHALL be derived solely from staging, with no source re-extraction.

#### Scenario: Rebuild
- WHEN Transform runs against existing staging
- THEN analytics is rebuilt with zero API calls and no dependency on raw

### Requirement: Optimizer-ready model
The star SHALL expose every input the team-optimizer reads — per-pokemon stats and types, move
power/accuracy/type/damage_class, the learnset, and the type-effectiveness multiplier — so the
algorithm needs no other source.

#### Scenario: Move score inputs available
- WHEN the optimizer scores a (pokemon, move, defending-type) triple
- THEN power, accuracy, STAB (via the pokemon's types), effectiveness, and the damage-class stat are
  all reachable as joins on the star

### Requirement: Transform stage placement
Transform SHALL run as a pipeline stage that reads only staging and writes only analytics, off by
default until implemented.

#### Scenario: Medallion boundary
- WHEN the Transform stage runs
- THEN it reads staging and writes analytics, sharing no in-memory state with other stages
