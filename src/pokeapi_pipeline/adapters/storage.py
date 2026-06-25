"""DuckDbStorage adapter: bronze raw + typed staging persistence."""

from collections.abc import Iterable, Iterator
from pathlib import Path

import duckdb
import msgspec

from pokeapi_pipeline.core.domain.mapping import struct_for
from pokeapi_pipeline.core.domain.records import RawRecord

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()

# entity_type -> staging table. 'pokemon-species' lands in staging.species.
_TABLES = {
    "pokemon": "pokemon",
    "pokemon-species": "species",
    "type": "type",
    "move": "move",
}


class DuckDbStorage:
    """One DuckDB connection; raw and staging schemas ensured on init."""

    def __init__(self, db_path: str) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(db_path)
        self._con.execute(_SCHEMA)

    def existing_raw_keys(self) -> set[str]:
        return {key for (key,) in self._con.execute("SELECT key FROM raw.records").fetchall()}

    def write_raw(self, records: Iterable[RawRecord]) -> int:
        rows = [
            (r.key, r.entity_type, msgspec.json.encode(r.payload).decode(), r.fetched_at)
            for r in records
        ]
        self._con.executemany(
            """
            INSERT INTO raw.records (key, entity_type, payload, fetched_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                entity_type = excluded.entity_type,
                payload = excluded.payload,
                fetched_at = excluded.fetched_at
            """,
            rows,
        )
        return len(rows)

    def read_raw(self, entity_type: str) -> Iterator[dict]:
        cursor = self._con.execute(
            "SELECT payload FROM raw.records WHERE entity_type = ?", [entity_type]
        )
        for (payload,) in cursor.fetchall():
            yield msgspec.json.decode(payload)

    def write_staging(self, entity_type: str, rows: Iterable[object]) -> int:
        table = _TABLES[entity_type]
        fields = struct_for(entity_type).__struct_fields__
        columns = ", ".join(f'"{f}"' for f in fields)
        placeholders = ", ".join(["?"] * len(fields))
        data = [
            [self._as_param(getattr(row, f)) for f in fields]  # struct values in column order
            for row in rows
        ]
        self._con.executemany(
            f"INSERT OR REPLACE INTO staging.{table} ({columns}) VALUES ({placeholders})", data
        )
        return len(data)

    @staticmethod
    def _as_param(value: object) -> object:
        return list(value) if isinstance(value, tuple) else value  # tuple slug -> DuckDB array

    def close(self) -> None:
        self._con.close()
