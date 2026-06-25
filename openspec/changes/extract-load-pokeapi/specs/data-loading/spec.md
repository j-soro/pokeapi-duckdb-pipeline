## ADDED Requirements

### Requirement: Interpret raw into staging
Load SHALL read raw payloads, decode and validate them with msgspec, and write typed staging rows.

#### Scenario: Payload projected to typed columns
- WHEN a pokemon raw payload is loaded
- THEN staging.pokemon holds the validated subset, with ids parsed from URLs and stats flattened

#### Scenario: Validation failure surfaced
- WHEN a raw payload violates the staging schema
- THEN Load raises a decode error instead of writing an invalid row

### Requirement: Typed staging without derivations
Staging tables SHALL contain only typed source fields, with no derived or computed columns.

#### Scenario: No derived fields
- WHEN staging is written
- THEN it holds source-derived columns only; aggregates are deferred to Transform

### Requirement: Nullable move power
The move staging schema SHALL allow a null power for status moves.

#### Scenario: Status move
- WHEN a move has no power
- THEN staging.move.power is null, not zero

### Requirement: Idempotent staging
Load SHALL upsert staging rows by primary key, so re-runs converge to the same state.

#### Scenario: Re-load is idempotent
- WHEN Load runs twice against the same raw
- THEN staging contains one row per entity with identical values
