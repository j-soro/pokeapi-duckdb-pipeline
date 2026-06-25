"""DuckDbStorage adapter and the raw->staging reshape/validate seam."""

from collections.abc import Iterable, Iterator
from pathlib import Path

import duckdb
import msgspec

from pokeapi_pipeline.models import Move, Pokemon, Species, Type
from pokeapi_pipeline.records import RawRecord

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


def _ref_id(url: str) -> int:
    """Trailing id of a resource url: '.../pokemon-species/6/' -> 6."""
    return int(url.rstrip("/").rsplit("/", 1)[1])


def _slots(items: list[dict], key: str) -> list[str]:
    """Slug names ordered by slot (slot is encoded by list position)."""
    return [item[key]["name"] for item in sorted(items, key=lambda i: i["slot"])]


def _names(items: list[dict]) -> list[str]:
    return [item["name"] for item in items]


def _english_flavor(entries: list[dict]) -> str | None:
    for entry in entries:
        if entry["language"]["name"] == "en":
            return " ".join(entry["flavor_text"].split())  # collapse \n\f and runs of space
    return None


def _reshape_pokemon(p: dict) -> dict:
    stats = {s["stat"]["name"]: s["base_stat"] for s in p["stats"]}
    return {
        "id": p["id"],
        "name": p["name"],
        "height": p["height"],
        "weight": p["weight"],
        "base_experience": p["base_experience"],
        "order": p["order"],
        "is_default": p["is_default"],
        "species_id": _ref_id(p["species"]["url"]),
        "types": _slots(p["types"], "type"),
        "abilities": _slots(p["abilities"], "ability"),
        "sprite_front_default": p["sprites"]["front_default"],
        "sprite_back_default": p["sprites"]["back_default"],
        "hp": stats["hp"],
        "attack": stats["attack"],
        "defense": stats["defense"],
        "special_attack": stats["special-attack"],
        "special_defense": stats["special-defense"],
        "speed": stats["speed"],
    }


def _reshape_species(p: dict) -> dict:
    evolves_from = p["evolves_from_species"]
    return {
        "id": p["id"],
        "name": p["name"],
        "order": p["order"],
        "generation_id": _ref_id(p["generation"]["url"]),
        "evolution_chain_id": _ref_id(p["evolution_chain"]["url"]),
        "evolves_from_id": _ref_id(evolves_from["url"]) if evolves_from else None,
        "is_legendary": p["is_legendary"],
        "is_mythical": p["is_mythical"],
        "is_baby": p["is_baby"],
        "capture_rate": p["capture_rate"],
        "base_happiness": p["base_happiness"],
        "gender_rate": p["gender_rate"],
        "hatch_counter": p["hatch_counter"],
        "has_gender_differences": p["has_gender_differences"],
        "forms_switchable": p["forms_switchable"],
        "growth_rate": p["growth_rate"]["name"],
        "color": p["color"]["name"],
        "shape": p["shape"]["name"] if p["shape"] else None,
        "habitat": p["habitat"]["name"] if p["habitat"] else None,
        "egg_groups": _names(p["egg_groups"]),
        "flavor_text": _english_flavor(p["flavor_text_entries"]),
    }


def _reshape_type(p: dict) -> dict:
    dr = p["damage_relations"]
    move_class = p["move_damage_class"]
    return {
        "id": p["id"],
        "name": p["name"],
        "generation_id": _ref_id(p["generation"]["url"]),
        "move_damage_class": move_class["name"] if move_class else None,
        "double_damage_to": _names(dr["double_damage_to"]),
        "double_damage_from": _names(dr["double_damage_from"]),
        "half_damage_to": _names(dr["half_damage_to"]),
        "half_damage_from": _names(dr["half_damage_from"]),
        "no_damage_to": _names(dr["no_damage_to"]),
        "no_damage_from": _names(dr["no_damage_from"]),
    }


def _reshape_move(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "power": p["power"],
        "accuracy": p["accuracy"],
        "pp": p["pp"],
        "priority": p["priority"],
        "effect_chance": p["effect_chance"],
        "type_id": _ref_id(p["type"]["url"]),
        "damage_class": p["damage_class"]["name"],
        "target": p["target"]["name"],
        "generation_id": _ref_id(p["generation"]["url"]),
    }


# entity_type -> (reshape fn, struct, staging table). 'pokemon-species' lands in staging.species.
_LOADERS: dict[str, tuple] = {
    "pokemon": (_reshape_pokemon, Pokemon, "pokemon"),
    "pokemon-species": (_reshape_species, Species, "species"),
    "type": (_reshape_type, Type, "type"),
    "move": (_reshape_move, Move, "move"),
}


def to_staging(entity_type: str, payload: dict) -> msgspec.Struct:
    """Reshape a raw payload and validate it against its struct (the validation gate)."""
    reshape, struct, _ = _LOADERS[entity_type]
    return msgspec.convert(reshape(payload), type=struct)


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
        _, struct, table = _LOADERS[entity_type]
        fields = struct.__struct_fields__
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
