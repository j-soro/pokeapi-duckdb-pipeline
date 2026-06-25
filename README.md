# pokeapi-pipeline

Extract & Load pipeline: **PokeAPI → DuckDB**, following the medallion convention
(`raw` → `staging`, with a deferred `marts`/Transform step delivered as a diagram).

> Work in progress. See `openspec/changes/extract-load-pokeapi/` for the proposal and design.

## Run

```bash
uv sync
uv run pipeline
```
