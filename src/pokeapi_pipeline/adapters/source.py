"""PokeApiSource — SourcePort adapter. All PokeAPI navigation is private here."""

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import hishel
import hishel.httpx
import httpx

from pokeapi_pipeline.config import Config
from pokeapi_pipeline.core.domain.records import RawRecord

_BASE_URL = "https://pokeapi.co/api/v2"
_CACHE_DIR = ".cache"
_TIMEOUT = 30.0
_TYPE_COUNT = 18
_MAX_ATTEMPTS = 3
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_REF = re.compile(r"/([\w-]+)/(\d+)/?$")  # ".../pokemon-species/6/" -> ("pokemon-species", "6")


class PokeApiSource:
    """Fetches pokemon and their referenced species/moves, plus the 18 types."""

    def __init__(self, config: Config, transport: httpx.BaseTransport | None = None) -> None:
        self._user_agent = config.user_agent
        self._request_delay = config.request_delay
        self._transport = transport or self._default_transport()

    def records(self, limit: int, existing: set[str]) -> Iterator[RawRecord]:
        with self._client() as client:
            refs: set[str] = set()
            # pass 1: pokemon drive discovery (fetched even when already captured, for their refs)
            for url in self._list_pokemon(client, limit):
                key = self._key(url)
                payload = self._get(client, url)
                refs |= self._references(payload)
                if key not in existing:
                    yield self._record(key, payload)
            # pass 2: the referenced species/moves + the fixed 18 types
            for key in sorted((refs | self._type_keys()) - existing):
                yield self._record(key, self._get(client, self._path(key)))

    @staticmethod
    def _default_transport() -> httpx.BaseTransport:
        Path(_CACHE_DIR).mkdir(parents=True, exist_ok=True)
        storage = hishel.SyncSqliteStorage(database_path=str(Path(_CACHE_DIR) / "hishel.db"))
        return hishel.httpx.SyncCacheTransport(
            next_transport=httpx.HTTPTransport(retries=2),
            storage=storage,
            # store-and-use: serve cached entries offline, without revalidation
            policy=hishel.SpecificationPolicy(hishel.CacheOptions(allow_stale=True)),
        )

    @contextmanager
    def _client(self) -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url=_BASE_URL,
            transport=self._transport,
            headers={"User-Agent": self._user_agent},  # default UA is 403'd by Cloudflare
            timeout=_TIMEOUT,
        ) as client:
            yield client

    def _get(self, client: httpx.Client, url: str) -> dict:
        for attempt in range(_MAX_ATTEMPTS):
            resp = client.get(url)
            if resp.status_code not in _RETRY_STATUSES or attempt == _MAX_ATTEMPTS - 1:
                resp.raise_for_status()
                if self._request_delay and not resp.extensions.get("hishel_from_cache"):
                    time.sleep(self._request_delay)  # throttle real hits only, not cache hits
                return resp.json()
            time.sleep(self._backoff(resp, attempt))
        raise AssertionError("unreachable")

    def _backoff(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("retry-after", "")
        if retry_after.isdigit():
            return float(retry_after)
        return max(self._request_delay, 0.5) * (attempt + 1)

    def _list_pokemon(self, client: httpx.Client, limit: int) -> list[str]:
        data = self._get(client, f"/pokemon?limit={limit}")
        return [r["url"] for r in data["results"]]

    def _references(self, payload: dict) -> set[str]:
        refs = {self._key(payload["species"]["url"])}
        refs |= {self._key(m["move"]["url"]) for m in payload["moves"]}
        return refs

    @staticmethod
    def _type_keys() -> set[str]:
        return {f"type:{i}" for i in range(1, _TYPE_COUNT + 1)}

    @staticmethod
    def _key(url: str) -> str:
        m = _REF.search(url)
        if m is None:
            raise ValueError(f"unparseable resource url: {url}")
        return f"{m[1]}:{m[2]}"

    @staticmethod
    def _path(key: str) -> str:
        entity_type, id_ = key.split(":", 1)
        return f"/{entity_type}/{id_}"

    @staticmethod
    def _record(key: str, payload: dict) -> RawRecord:
        return RawRecord(
            key=key,
            entity_type=key.split(":", 1)[0],
            payload=payload,
            fetched_at=datetime.now(UTC),
        )
