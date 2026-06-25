"""Runtime configuration."""
from __future__ import annotations

from pathlib import Path

import msgspec


class Config(msgspec.Struct, frozen=True):
    db_path: str = "data/pokemon.duckdb"
    limit: int = 151
    user_agent: str = "pokeapi-pipeline/0.1"
    request_delay: float = 0.1                       # seconds between API calls
    force_refresh: bool = False                      # re-fetch even if already in raw
    stages: tuple[str, ...] = ("extract", "load")    # transform off by default


def load_config(path: str = "config.toml") -> Config:
    return msgspec.toml.decode(Path(path).read_bytes(), type=Config)
