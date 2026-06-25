## ADDED Requirements

### Requirement: Config-driven runs
The pipeline SHALL be driven entirely by config, with no CLI arguments, including which stages run.

#### Scenario: Stage selection from config
- WHEN config sets stages to ["extract", "load"]
- THEN only Extract and Load run, and Transform is skipped

### Requirement: Stage isolation via medallion layers
Stages SHALL communicate only through the DuckDB layers, never by passing data in memory.

#### Scenario: Load reads raw, not Extract output
- WHEN Load runs
- THEN it reads from raw and does not depend on Extract's in-memory state

### Requirement: Single-stage execution
The pipeline SHALL support running a stage in isolation against existing layers.

#### Scenario: Load-only run
- WHEN config selects only ["load"] and raw is already populated
- THEN staging is rebuilt with zero API calls
