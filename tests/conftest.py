"""Shared fixtures: real captured payloads, an offline PokeAPI transport, an in-memory store."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from pokeapi_pipeline.records import RawRecord
from pokeapi_pipeline.storage import DuckDbStorage

_FIXTURES = Path(__file__).parent / "fixtures"
_HOST = "https://pokeapi.co/api/v2"

Handler = Callable[[httpx.Request], httpx.Response]


def _load_fixtures() -> dict[str, dict]:
    """{'pokemon:1': payload, 'move:13': payload, ...} from the fixtures tree."""
    return {
        f"{path.parent.name}:{path.stem}": json.loads(path.read_text())
        for path in _FIXTURES.rglob("*.json")
    }


@pytest.fixture
def fixtures() -> dict[str, dict]:
    return _load_fixtures()


@pytest.fixture
def pokemon_ids(fixtures: dict[str, dict]) -> list[int]:
    return sorted(int(k.split(":")[1]) for k in fixtures if k.startswith("pokemon:"))


@pytest.fixture
def full_limit(pokemon_ids: list[int]) -> int:
    """A limit covering every captured pokemon."""
    return len(pokemon_ids)


@pytest.fixture
def make_handler() -> Callable[[dict[str, dict], list[int]], Handler]:
    """Factory for a MockTransport handler that replays the fixtures offline."""

    def factory(fixtures: dict[str, dict], pokemon_ids: list[int]) -> Handler:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path.removeprefix("/api/v2").strip("/")
            if path == "pokemon":  # listing (id-less path); query carries the limit
                limit = int(request.url.params.get("limit", len(pokemon_ids)))
                results = [{"url": f"{_HOST}/pokemon/{i}/"} for i in pokemon_ids[:limit]]
                return httpx.Response(200, json={"results": results})
            entity, id_ = path.split("/")
            return httpx.Response(200, json=fixtures[f"{entity}:{id_}"])

        return handler

    return factory


@pytest.fixture
def mock_transport(
    fixtures: dict[str, dict],
    pokemon_ids: list[int],
    make_handler: Callable[[dict[str, dict], list[int]], Handler],
) -> httpx.MockTransport:
    return httpx.MockTransport(make_handler(fixtures, pokemon_ids))


@pytest.fixture
def raw_records() -> list[RawRecord]:
    return [
        RawRecord(
            key=f"{path.parent.name}:{path.stem}",
            entity_type=path.parent.name,
            payload=json.loads(path.read_text()),
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for path in sorted(_FIXTURES.rglob("*.json"))
    ]


@pytest.fixture
def storage() -> Iterator[DuckDbStorage]:
    store = DuckDbStorage(":memory:")
    yield store
    store.close()
