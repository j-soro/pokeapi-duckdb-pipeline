"""Regenerate the test fixtures from the live PokeAPI (run manually):

    uv run python -m tests.capture_fixtures

One pokemon (moves trimmed), its species, those moves, and the 18 types, written
to tests/fixtures/<entity>/<id>.json and replayed offline by the tests.
"""

import json
from pathlib import Path

import httpx

_BASE = "https://pokeapi.co/api/v2"
_HEADERS = {"User-Agent": "pokeapi-pipeline-fixtures/0.1"}
_FIXTURES = Path(__file__).parent / "fixtures"
_POKEMON_ID = 1
_MOVES_PER_POKEMON = 3
_TYPE_COUNT = 18


def _save(entity: str, id_: int, payload: dict) -> None:
    path = _FIXTURES / entity / f"{id_}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _ref_id(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[1])


def main() -> None:
    with httpx.Client(base_url=_BASE, headers=_HEADERS, timeout=30.0) as client:
        pokemon = client.get(f"/pokemon/{_POKEMON_ID}").raise_for_status().json()
        pokemon["moves"] = pokemon["moves"][:_MOVES_PER_POKEMON]  # trim to keep fixtures small
        _save("pokemon", _POKEMON_ID, pokemon)

        species_id = _ref_id(pokemon["species"]["url"])
        species = client.get(f"/pokemon-species/{species_id}").raise_for_status().json()
        _save("pokemon-species", species_id, species)

        for entry in pokemon["moves"]:
            move_id = _ref_id(entry["move"]["url"])
            _save("move", move_id, client.get(f"/move/{move_id}").raise_for_status().json())

        for type_id in range(1, _TYPE_COUNT + 1):
            _save("type", type_id, client.get(f"/type/{type_id}").raise_for_status().json())


if __name__ == "__main__":
    main()
