"""DuckDbStorage and raw->staging reshape/validate tests, over the real fixtures.

Every captured entity must round-trip raw -> reshape -> validated staging row.
"""

from pathlib import Path

import msgspec
import pytest

from pokeapi_pipeline.models import Pokemon, Type
from pokeapi_pipeline.records import RawRecord
from pokeapi_pipeline.storage import DuckDbStorage, to_staging

_ENTITY_TYPES = ("pokemon", "pokemon-species", "type", "move")


def _payload(raw_records: list[RawRecord], key: str) -> dict:
    return next(r.payload for r in raw_records if r.key == key)


def _count(storage: DuckDbStorage, table: str) -> int:
    row = storage._con.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return row[0]


def _load_all(storage: DuckDbStorage) -> dict[str, int]:
    """read_raw -> to_staging (validate) -> write_staging for every entity type."""
    written = {}
    for entity in _ENTITY_TYPES:
        rows = [to_staging(entity, p) for p in storage.read_raw(entity)]
        written[entity] = storage.write_staging(entity, rows)
    return written


# --- raw layer --------------------------------------------------------------


def test_write_raw_roundtrip(storage: DuckDbStorage, raw_records: list[RawRecord]) -> None:
    n = storage.write_raw(raw_records)
    assert n == len(raw_records)
    assert storage.existing_raw_keys() == {r.key for r in raw_records}  # completeness oracle


def test_read_raw_filters_by_entity_type(
    storage: DuckDbStorage, raw_records: list[RawRecord]
) -> None:
    storage.write_raw(raw_records)
    for entity in _ENTITY_TYPES:
        got = list(storage.read_raw(entity))
        expected = sum(1 for r in raw_records if r.entity_type == entity)
        assert len(got) == expected


def test_existing_raw_keys_drives_resume(
    storage: DuckDbStorage, raw_records: list[RawRecord]
) -> None:
    half = raw_records[:5]
    storage.write_raw(half)
    assert storage.existing_raw_keys() == {r.key for r in half}  # only what's stored


# --- reshape + validation ---------------------------------------------------


def test_reshape_pokemon_values(raw_records: list[RawRecord]) -> None:
    pk = to_staging("pokemon", _payload(raw_records, "pokemon:1"))
    assert isinstance(pk, Pokemon)
    assert pk.types == ("grass", "poison")  # slot order preserved
    assert pk.species_id == 1  # url -> id
    assert pk.special_attack == 65  # hyphenated stat flattened


def test_reshape_type_lists_and_null(raw_records: list[RawRecord]) -> None:
    ty = to_staging("type", _payload(raw_records, "type:1"))  # normal
    assert isinstance(ty, Type)
    assert ty.name == "normal"
    assert ty.no_damage_to == ("ghost",)
    assert ty.double_damage_to == ()  # empty tuple, not null
    assert ty.move_damage_class == "physical"  # nested name extracted


def test_to_staging_rejects_wrong_type(raw_records: list[RawRecord]) -> None:
    bad = dict(_payload(raw_records, "pokemon:1"))
    bad["height"] = "tall"  # int field given a str
    with pytest.raises(msgspec.ValidationError):
        to_staging("pokemon", bad)


def test_to_staging_rejects_missing_required(raw_records: list[RawRecord]) -> None:
    bad = dict(_payload(raw_records, "move:13"))
    bad["name"] = None  # non-nullable
    with pytest.raises(msgspec.ValidationError):
        to_staging("move", bad)


def test_reshape_species_without_english_flavor(raw_records: list[RawRecord]) -> None:
    payload = dict(_payload(raw_records, "pokemon-species:1"))
    payload["flavor_text_entries"] = []  # no en entry -> nullable flavor_text
    sp = to_staging("pokemon-species", payload)
    assert msgspec.to_builtins(sp)["flavor_text"] is None


def test_reshape_type_with_null_damage_class(raw_records: list[RawRecord]) -> None:
    payload = dict(_payload(raw_records, "type:1"))
    payload["move_damage_class"] = None  # newer types have no damage class
    ty = to_staging("type", payload)
    assert isinstance(ty, Type)
    assert ty.move_damage_class is None


# --- staging layer + completeness -------------------------------------------


def test_every_entity_loads_to_staging(
    storage: DuckDbStorage, raw_records: list[RawRecord]
) -> None:
    storage.write_raw(raw_records)
    written = _load_all(storage)
    # every captured entity is staged, counts matching what we read from raw
    assert written == {
        "pokemon": 1,
        "pokemon-species": 1,
        "type": 18,
        "move": 3,
    }
    assert _count(storage, "staging.type") == 18
    assert _count(storage, "staging.pokemon") == 1


def test_init_creates_db_file(tmp_path: Path, raw_records: list[RawRecord]) -> None:
    db = tmp_path / "nested" / "pokemon.duckdb"
    store = DuckDbStorage(str(db))
    store.write_raw(raw_records[:1])
    store.close()
    assert db.exists()  # parent dir created, file persisted


def test_load_is_idempotent(storage: DuckDbStorage, raw_records: list[RawRecord]) -> None:
    storage.write_raw(raw_records)
    storage.write_raw(raw_records)  # re-extract: upsert by key
    _load_all(storage)
    _load_all(storage)  # re-load: INSERT OR REPLACE by id
    assert len(storage.existing_raw_keys()) == len(raw_records)
    assert _count(storage, "staging.type") == 18
    assert _count(storage, "staging.move") == 3
    assert _count(storage, "staging.pokemon") == 1
