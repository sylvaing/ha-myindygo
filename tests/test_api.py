"""Tests for the MyIndygo API client, with a fake aiohttp session."""

from __future__ import annotations

import base64
from collections import deque
from typing import Any

import aiohttp
import pytest

from custom_components.myindygo.api import (
    MyIndygoApiClient,
    MyIndygoAuthError,
    MyIndygoConnectionError,
    child_id,
)
from custom_components.myindygo.const import DEFAULT_CLIENT_ID

BASE = "https://example.test"


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def json(self, content_type: str | None = None) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSession:
    """Replays queued responses per (method, path) and records every call."""

    def __init__(self) -> None:
        self.queue: dict[tuple[str, str], deque] = {}
        self.calls: list[dict[str, Any]] = []

    def add(self, method: str, path: str, status: int = 200, payload: Any = None) -> None:
        self.queue.setdefault((method, path), deque()).append((status, payload))

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        path = url.removeprefix(BASE)
        self.calls.append({"method": method, "path": path, **kwargs})
        status, payload = self.queue[(method, path)].popleft()
        if isinstance(payload, aiohttp.ClientError):
            raise payload
        return FakeResponse(status, payload)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("POST", url, **kwargs)


TOKEN = {"access_token": "abc", "token_type": "Bearer", "expires_in": 5184000}


def make_client(session: FakeSession, client_id: str | None = None) -> MyIndygoApiClient:
    return MyIndygoApiClient(session, " User@Example.com ", "pw", client_id=client_id, base_url=BASE)  # type: ignore[arg-type]


async def test_login_uses_basic_client_id_and_password_grant() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    client = make_client(session)

    await client.async_login()

    call = session.calls[0]
    assert call["json"] == {"grant_type": "password", "username": "user@example.com", "password": "pw"}
    expected = base64.b64encode(DEFAULT_CLIENT_ID.encode()).decode()
    assert call["headers"]["Authorization"] == f"Basic {expected}"
    assert call["headers"]["Accept"] == "version=2.7"
    assert client.authorization == "Bearer abc"


async def test_login_with_overridden_client_id() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    await make_client(session, client_id="other:secret").async_login()
    expected = base64.b64encode(b"other:secret").decode()
    assert session.calls[0]["headers"]["Authorization"] == f"Basic {expected}"


@pytest.mark.parametrize("status", [400, 401, 403, 500])
async def test_login_rejected(status: int) -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", status=status, payload={"_": "x"})
    with pytest.raises(MyIndygoAuthError):
        await make_client(session).async_login()


async def test_login_unreachable() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=aiohttp.ClientConnectionError("down"))
    with pytest.raises(MyIndygoConnectionError):
        await make_client(session).async_login()


async def test_request_sends_bearer_and_query_params() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("GET", "/api/getModuleWithHisUsers", payload={"id": "m1"})
    client = make_client(session)

    assert await client.async_get_module("m1") == {"id": "m1"}

    call = session.calls[1]
    assert call["params"] == {"module": "m1"}
    assert call["headers"]["Authorization"] == "Bearer abc"


async def test_relogin_once_on_401() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("GET", "/api/getUserWithHisModules", status=401, payload=None)
    session.add("POST", "/oauth2/token", payload={**TOKEN, "access_token": "new"})
    session.add("GET", "/api/getUserWithHisModules", payload={"modules": []})
    client = make_client(session)

    assert await client.async_get_user_with_modules() == {"modules": []}
    assert session.calls[-1]["headers"]["Authorization"] == "Bearer new"


async def test_second_401_raises_auth_error() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("GET", "/api/getUserWithHisModules", status=401, payload=None)
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("GET", "/api/getUserWithHisModules", status=401, payload=None)
    with pytest.raises(MyIndygoAuthError):
        await make_client(session).async_get_user_with_modules()


async def test_api_error_in_200_answer() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", "/api/getPoolStatus", payload={"error": {"code": "deprecated_application_version"}})
    with pytest.raises(MyIndygoConnectionError, match="deprecated_application_version"):
        await make_client(session).async_get_pool_status("p1")


async def test_get_pools_and_body() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", "/api/getUser", payload={"id": "u", "pools": [{"id": "p1"}]})
    assert await make_client(session).async_get_pools() == [{"id": "p1"}]
    assert session.calls[1]["json"] == {"attributesToPopulate": ["pools"]}


async def test_device_relay_url_for_child_and_date_header() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("GET", "/api/module/10000007ABCD0001/status/ABCDEF", payload={"pool": []})
    client = make_client(session)

    assert await client.async_get_device("10000007ABCD0001", "status", "150302ABCDEF0001") == {"pool": []}
    assert "T" in session.calls[1]["headers"]["Date"]


async def test_device_relay_url_for_gateway() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("GET", "/api/module/10000007ABCD0001/information", payload={"mtype": "10"})
    assert await make_client(session).async_get_device("10000007ABCD0001", "information") == {"mtype": "10"}


def test_child_id() -> None:
    assert child_id("150302ABCDEF0001") == "ABCDEF"
    assert child_id("FD0001020200112233AABBCC0001") == "AABBCC"
    with pytest.raises(ValueError):
        child_id("short")
