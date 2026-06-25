## ADDED Requirements

### Requirement: Linked-resource capture
The pipeline SHALL fetch the configured number of pokemon, then the species and moves they
reference, plus all 18 types, writing each as a raw payload.

#### Scenario: Default Gen-1 scope
- WHEN the pipeline runs with the default scope (151 pokemon)
- THEN raw contains every referenced pokemon, species, and move, plus the 18 types

#### Scenario: Moves discovered via references
- WHEN a pokemon payload lists moves
- THEN those move keys are fetched, since moves cannot be enumerated up front

### Requirement: Faithful capture
Extract SHALL store API payloads verbatim, without decoding or reshaping them.

#### Scenario: Payload stored as-is
- WHEN an entity is fetched
- THEN its payload is persisted unchanged, with no validation applied during capture

### Requirement: Resumable extraction
Extract SHALL skip keys already present in raw unless force_refresh is set.

#### Scenario: Re-run after interruption
- WHEN a run is interrupted and restarted
- THEN only entities missing from raw are fetched

#### Scenario: Forced refresh
- WHEN force_refresh is true
- THEN all in-scope entities are re-fetched regardless of raw contents

### Requirement: Fair-use fetching
Extract SHALL send a custom User-Agent, delay between requests, and cache HTTP responses.

#### Scenario: Custom User-Agent
- WHEN a request is sent to PokeAPI
- THEN it carries the configured User-Agent, since the default client UA is rejected by Cloudflare
