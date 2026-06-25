"""PokeApiSource navigation tests; real captured fixtures replayed via MockTransport.

The fixtures on disk are the oracle: the source must yield exactly the captured entities.
"""

from collections.abc import Callable

import httpx
import pytest

from pokeapi_pipeline.adapters.source import PokeApiSource
from pokeapi_pipeline.config import Config

_HOST = "https://pokeapi.co/api/v2"

Handler = Callable[[httpx.Request], httpx.Response]
MakeHandler = Callable[[dict[str, dict], list[int]], Handler]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip throttle/backoff delays so the suite is fast."""
    monkeypatch.setattr("pokeapi_pipeline.adapters.source.time.sleep", lambda _s: None)


@pytest.fixture
def source(mock_transport: httpx.MockTransport) -> PokeApiSource:
    return PokeApiSource(Config(request_delay=0.0), transport=mock_transport)


def test_fetches_exactly_the_captured_universe(
    source: PokeApiSource, fixtures: dict[str, dict], full_limit: int
) -> None:
    keys = {r.key for r in source.records(limit=full_limit, existing=set())}
    assert keys == set(fixtures)  # every referenced entity + 18 types, nothing missed or extra


def test_all_four_entity_types_present(source: PokeApiSource, full_limit: int) -> None:
    entity_types = {r.entity_type for r in source.records(limit=full_limit, existing=set())}
    assert entity_types == {"pokemon", "pokemon-species", "move", "type"}


def test_resume_skips_existing_but_keeps_discovery(
    source: PokeApiSource, fixtures: dict[str, dict], full_limit: int
) -> None:
    a_move = next(k for k in fixtures if k.startswith("move:"))
    existing = {a_move}
    keys = {r.key for r in source.records(limit=full_limit, existing=existing)}
    assert a_move not in keys  # skipped
    assert keys == set(fixtures) - existing  # everything else still discovered


def test_entity_type_derived_from_key(
    source: PokeApiSource, fixtures: dict[str, dict], full_limit: int
) -> None:
    by_key = {r.key: r for r in source.records(limit=full_limit, existing=set())}
    species_key = next(k for k in fixtures if k.startswith("pokemon-species:"))
    type_key = next(k for k in fixtures if k.startswith("type:"))
    assert by_key[species_key].entity_type == "pokemon-species"
    assert by_key[type_key].entity_type == "type"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{_HOST}/pokemon-species/6/", "pokemon-species:6"),
        (f"{_HOST}/move/14", "move:14"),
        ("/type/3/", "type:3"),
    ],
)
def test_key_parsing(url: str, expected: str) -> None:
    assert PokeApiSource._key(url) == expected


def test_key_parsing_rejects_unparseable() -> None:
    with pytest.raises(ValueError, match="unparseable"):
        PokeApiSource._key(f"{_HOST}/pokemon/")


def test_retries_then_succeeds(
    fixtures: dict[str, dict], pokemon_ids: list[int], make_handler: MakeHandler
) -> None:
    inner = make_handler(fixtures, pokemon_ids)
    calls = {"list": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path.removeprefix("/api/v2").strip("/") == "pokemon":
            calls["list"] += 1
            if calls["list"] < 3:
                return httpx.Response(503)
        return inner(request)

    source = PokeApiSource(Config(request_delay=0.0), transport=httpx.MockTransport(flaky))
    keys = {r.key for r in source.records(limit=len(pokemon_ids), existing=set())}
    assert calls["list"] == 3  # 503, 503, 200
    assert keys == set(fixtures)


def test_default_transport_builds_cache_transport() -> None:
    # no transport injected -> the real hishel cache transport is constructed without error
    source = PokeApiSource(Config())
    assert type(source._transport).__name__ == "SyncCacheTransport"


def test_throttles_real_hits(
    fixtures: dict[str, dict],
    pokemon_ids: list[int],
    full_limit: int,
    make_handler: MakeHandler,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("pokeapi_pipeline.adapters.source.time.sleep", slept.append)
    source = PokeApiSource(
        Config(request_delay=0.5),
        transport=httpx.MockTransport(make_handler(fixtures, pokemon_ids)),
    )
    list(source.records(limit=full_limit, existing=set()))
    assert slept and all(s == 0.5 for s in slept)  # every non-cache hit is throttled


def test_backoff_honors_numeric_retry_after() -> None:
    source = PokeApiSource(
        Config(request_delay=0.0), transport=httpx.MockTransport(lambda _r: httpx.Response(200))
    )
    assert source._backoff(httpx.Response(503, headers={"retry-after": "2"}), 0) == 2.0
    assert (
        source._backoff(httpx.Response(503), 1) == 1.0
    )  # no header -> max(delay, 0.5) * (attempt + 1)
