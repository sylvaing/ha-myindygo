"""Async client for the MyIndygo cloud API.

The protocol was documented from the MyIndygo Android app and verified on a real account.
Two families of URLs share the same bearer token:

* platform API: ``/api/<verb>`` (account, modules, pools, programs, IPX data);
* device relay: ``/api/module/<gateway SN>/<endpoint>[/<child id>]``, which forwards the
  request to the gateway's local v2 API in real time.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime
from typing import Any

import aiohttp

from .const import API_BASE_URL, API_VERSION, DEFAULT_CLIENT_ID

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=45)
USER_AGENT = "ha-myindygo (Home Assistant custom integration)"


class MyIndygoError(Exception):
    """Base error of the MyIndygo client."""


class MyIndygoConnectionError(MyIndygoError):
    """The server could not be reached or answered unexpectedly."""


class MyIndygoAuthError(MyIndygoError):
    """The credentials (or the client identifier) were rejected."""


def child_id(serial_number: str) -> str:
    """Return the 6-character id of a radio child, as used in device relay URLs.

    Example: ``150302ABCDEF0001`` -> ``ABCDEF``.
    """
    if len(serial_number) < 10:
        raise ValueError(f"Unexpected serial number: {serial_number!r}")
    return serial_number[-10:-4]


class MyIndygoApiClient:
    """Minimal client for the MyIndygo cloud (reads, plus the manual commands of a pool controller)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        client_id: str | None = None,
        base_url: str = API_BASE_URL,
    ) -> None:
        self._session = session
        self._email = email.strip().lower()
        self._password = password
        self._client_id = client_id or DEFAULT_CLIENT_ID
        self._base_url = base_url.rstrip("/")
        self._authorization: str | None = None
        self._login_lock = asyncio.Lock()

    @property
    def authorization(self) -> str | None:
        """Current ``Authorization`` header value (``Bearer …``), if logged in."""
        return self._authorization

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": f"version={API_VERSION}",
            "Cache-Control": "no-cache, no-transform",
            "User-Agent": USER_AGENT,
        }

    async def async_login(self) -> None:
        """Get a user token with the OAuth2 password grant.

        Raises MyIndygoAuthError when the credentials or the client identifier are rejected.
        """
        basic = base64.b64encode(self._client_id.encode()).decode()
        headers = {**self._headers(), "Authorization": f"Basic {basic}"}
        body = {"grant_type": "password", "username": self._email, "password": self._password}
        try:
            async with self._session.post(
                f"{self._base_url}/oauth2/token", json=body, headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                # The app treats HTTP 500 as "wrong login or password"; 400/401/403 cover the
                # client identifier and the usual OAuth2 errors.
                if resp.status in (400, 401, 403, 500):
                    raise MyIndygoAuthError(f"Login rejected (HTTP {resp.status})")
                if resp.status != 200:
                    raise MyIndygoConnectionError(f"Unexpected login answer (HTTP {resp.status})")
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MyIndygoConnectionError(f"Cannot reach MyIndygo: {err}") from err

        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise MyIndygoAuthError("Login answer has no access token")
        self._authorization = f"{payload.get('token_type') or 'Bearer'} {token}"
        _LOGGER.debug("Logged in to MyIndygo (token valid %s s)", payload.get("expires_in"))

    async def _async_ensure_login(self, failed_authorization: str | None = None) -> None:
        async with self._login_lock:
            # Another caller may have refreshed the token while we waited for the lock.
            if self._authorization is None or self._authorization == failed_authorization:
                await self.async_login()

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Send an authenticated request, logging in again once on HTTP 401."""
        await self._async_ensure_login()
        for attempt in (1, 2):
            authorization = self._authorization
            headers = {**self._headers(), "Authorization": authorization or "", **(extra_headers or {})}
            try:
                async with self._session.request(
                    method,
                    f"{self._base_url}{path}",
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status in (401, 403):
                        if attempt == 1:
                            await self._async_ensure_login(failed_authorization=authorization)
                            continue
                        raise MyIndygoAuthError(f"{path}: access denied (HTTP {resp.status})")
                    if resp.status != 200:
                        raise MyIndygoConnectionError(f"{path}: HTTP {resp.status}")
                    payload = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise MyIndygoConnectionError(f"{path}: {err}") from err
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                raise MyIndygoConnectionError(f"{path}: API error {payload['error'].get('code')}")
            return payload
        raise MyIndygoAuthError(f"{path}: access denied")  # pragma: no cover

    # Platform API -------------------------------------------------------------------------

    async def async_get_user_with_modules(self) -> dict[str, Any]:
        """Return the user with the list of its modules (``modules``)."""
        return await self._async_request("GET", "/api/getUserWithHisModules")

    async def async_get_module(self, module_id: str) -> dict[str, Any]:
        """Return one module with its inputs, outputs and IPX data."""
        return await self._async_request("GET", "/api/getModuleWithHisUsers", params={"module": module_id})

    async def async_send_ipx_data(self, output_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Request a setting of an IPX output (``POST /api/outputs/<output id>/ipxData``).

        ``values`` is the ``ipxData`` object, e.g. ``{"pHSetpoint": 7.3}`` (one key per request,
        like the app). The platform stores it in ``pendingIpxData`` until the device picks it up.
        The app treats an answer with an ``err`` key as a failure; the answer is not used otherwise.
        """
        payload = await self._async_request(
            "POST", f"/api/outputs/{output_id}/ipxData", json={"ipxData": values}
        )
        if isinstance(payload, dict) and payload.get("err"):
            raise MyIndygoConnectionError(f"/api/outputs/{output_id}/ipxData: {payload['err']}")
        return payload if isinstance(payload, dict) else {}

    async def async_get_pools(self) -> list[dict[str, Any]]:
        """Return the pools of the user."""
        user = await self._async_request("POST", "/api/getUser", json={"attributesToPopulate": ["pools"]})
        return user.get("pools", []) if isinstance(user, dict) else []

    async def async_get_pool_status(self, pool_id: str) -> dict[str, Any]:
        """Return a pool with its latest measures (``status``)."""
        return await self._async_request(
            "POST", "/api/getPoolStatus", json={"id": pool_id, "attributesToPopulate": ["modules"]}
        )

    async def async_get_programs(self, module_id: str) -> dict[str, Any]:
        """Return the programs of a module as stored by the platform."""
        return await self._async_request("GET", "/api/getPrograms", params={"id": module_id})

    # Device relay -------------------------------------------------------------------------

    async def async_get_device(
        self, gateway_serial: str, endpoint: str, child_serial: str | None = None
    ) -> dict[str, Any]:
        """Read a device endpoint (``status``, ``programs``, ``information``, ``inventory``…).

        The request goes through the cloud to the gateway, which answers from its own state
        or, for a radio child (``child_serial``), from the last radio exchange.
        """
        path = _relay_path(gateway_serial, endpoint, child_serial)
        return await self._async_request("GET", path, extra_headers=_date_header())

    async def async_send_manual_command(
        self, gateway_serial: str, child_serial: str, command: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a manual command to an output of a pool controller (``POST …/manual/<child id>``).

        ``command`` is the ``pool`` object of the device API, e.g.
        ``{"index": 0, "action": 2, "manualDuration": 3600}``. The relay answers with the
        controller ``status``; ``radio: ["cmd"]`` means the command is still waiting for the
        radio link, so the answer does not prove that the output switched.
        """
        path = _relay_path(gateway_serial, "manual", child_serial)
        payload = await self._async_request(
            "POST", path, json={"pool": command}, extra_headers=_date_header()
        )
        return payload if isinstance(payload, dict) else {}


def _relay_path(gateway_serial: str, endpoint: str, child_serial: str | None) -> str:
    path = f"/api/module/{gateway_serial}/{endpoint}"
    if child_serial:
        path += f"/{child_id(child_serial)}"
    return path


def _date_header() -> dict[str, str]:
    return {"Date": datetime.now().astimezone().isoformat(timespec="seconds")}
