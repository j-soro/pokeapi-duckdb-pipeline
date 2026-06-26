"""Runtime configuration."""

from pathlib import Path

import msgspec


class Config(msgspec.Struct, frozen=True):
    db_path: str = "data/pokemon.duckdb"
    limit: int = 151
    user_agent: str = "pokeapi-pipeline/0.1"
    request_delay: float = 0.1  # seconds between API calls
    stages: tuple[str, ...] = ("extract", "load")  # transform off by default
    http_cache: bool = True  # persistent hishel cache; off = always hit the network
    log_level: str = "INFO"


def load_config(path: str = "config.toml") -> Config:
    return msgspec.toml.decode(Path(path).read_bytes(), type=Config)
