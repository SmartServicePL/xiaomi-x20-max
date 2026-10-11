"""Independent Xiaomi OAuth and MIoT HTTP transport for the X20 Max.

The Xiaomi cloud API interface is used only inside Home Assistant for
non-commercial purposes. See LICENSE_XIAOMI.md in the project root.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import MODEL, PropertyRef

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "2882303761520251711"
OAUTH_HOST = "ha.api.io.mi.com"
OAUTH_REDIRECT_URL = "http://homeassistant.local:8123"
STORE_KEY = "xiaomi_x20_max.oauth"
REFRESH_MARGIN = 300
TOKEN_EXPIRES_RATIO = 0.7
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class X20MaxCloudError(Exception):
    """Base cloud transport error."""


class X20MaxAuthError(X20MaxCloudError):
    """OAuth credentials are missing or were rejected by Xiaomi.

    Unlike a plain X20MaxCloudError this is not a transient failure: it is
    only raised when there is no grant at all or Xiaomi explicitly refused
    to refresh it, so the user has to act (re-authenticate).
    """


class X20MaxActionError(X20MaxCloudError):
    """A MIoT action was delivered but the device returned a non-zero code."""

    def __init__(self, siid: int, aiid: int, code: Any) -> None:
        super().__init__(f"Akcja MIoT {siid}.{aiid}: kod {code}")
        self.siid = siid
        self.aiid = aiid
        self.code = code


def _load_bootstrap_auth(config_path: str) -> tuple[str, dict[str, Any]] | None:
    """Read the existing Xiaomi OAuth grant from the Xiaomi Home storage.

    Xiaomi Home appends a 32-byte integrity trailer to its JSON dictionary, so
    only the JSON prefix is decoded. No Xiaomi Home Python module is imported.
    """
    root = Path(config_path) / ".storage" / "xiaomi_home" / "miot_config"
    for path in sorted(root.glob("*_*.dict")):
        try:
            raw = path.read_bytes()
            end = raw.rfind(b"}")
            if end < 0:
                continue
            data = json.loads(raw[: end + 1])
            auth = data.get("auth_info")
            if not isinstance(auth, dict):
                continue
            if not all(auth.get(key) for key in ("access_token", "refresh_token")):
                continue
            server = path.stem.rsplit("_", 1)[-1]
            return server, auth
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    return None


class X20MaxCloud:
    """Small, shared OAuth client for the model-specific integration."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._session = async_get_clientsession(hass)
        self._store: Store[dict[str, Any]] = Store(hass, 1, STORE_KEY)
        self.server = "de"
        self.auth: dict[str, Any] = {}
        self._auth_lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return bool(
            self.auth.get("access_token") and self.auth.get("refresh_token")
        )

    async def async_initialize(self) -> None:
        """Load private credentials or import the current grant once."""
        stored = await self._store.async_load()
        if isinstance(stored, dict) and stored.get("auth"):
            self.server = str(stored.get("server") or "de")
            self.auth = dict(stored["auth"])
        elif not await self._async_import_bootstrap():
            raise X20MaxAuthError(
                "Brak danych OAuth. Najpierw zaloguj konto Xiaomi."
            )
        await self._async_ensure_token()

    async def async_reimport(self) -> None:
        """Import the current Xiaomi Home grant again (re-authentication).

        Used by the re-authentication flow after the user has signed in again
        in the official Xiaomi Home integration. The imported grant replaces
        the private one even when it looks identical, and is then validated by
        the caller with a real cloud request.
        """
        async with self._auth_lock:
            if not await self._async_import_bootstrap(force=True):
                raise X20MaxAuthError(
                    "Brak danych OAuth integracji Xiaomi Home"
                )
        await self._async_ensure_token()

    async def _async_import_bootstrap(self, *, force: bool = False) -> bool:
        """Adopt the grant stored by Xiaomi Home.

        Without ``force`` the grant is adopted only when it differs from the
        private one (a different refresh token), so a grant that Xiaomi has
        already rejected is never retried in a loop.
        """
        bootstrap = await self.hass.async_add_executor_job(
            _load_bootstrap_auth, self.hass.config.config_dir
        )
        if bootstrap is None:
            return False
        server, auth = bootstrap
        if (
            not force
            and self.auth
            and auth.get("refresh_token") == self.auth.get("refresh_token")
        ):
            return False
        self.server, self.auth = server, dict(auth)
        await self._async_save()
        _LOGGER.info(
            "Imported Xiaomi OAuth grant into the independent X20 Max store"
        )
        return True

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"server": self.server, "auth": self.auth}
        )

    @property
    def _host(self) -> str:
        return OAUTH_HOST if self.server == "cn" else f"{self.server}.{OAUTH_HOST}"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Host": self._host,
            "X-Client-BizId": "haapi",
            "Content-Type": "application/json",
            "Authorization": f"Bearer{self.auth['access_token']}",
            "X-Client-AppId": CLIENT_ID,
        }

    def _token_valid(self) -> bool:
        return (
            int(self.auth.get("expires_ts") or 0)
            > int(time.time()) + REFRESH_MARGIN
        )

    async def _async_ensure_token(self, *, force: bool = False) -> None:
        if not self.ready:
            raise X20MaxAuthError("Brak danych OAuth Xiaomi")
        if not force and self._token_valid():
            return
        async with self._auth_lock:
            if not force and self._token_valid():
                return
            try:
                await self._async_refresh_token()
            except X20MaxAuthError:
                # Xiaomi refused the private refresh token. If Xiaomi Home
                # holds a newer grant (for example after the user signed in
                # again there), adopt it once and retry before giving up.
                if not await self._async_import_bootstrap():
                    raise
                if self._token_valid():
                    return
                await self._async_refresh_token()

    async def _async_refresh_token(self) -> None:
        """Exchange the refresh token. Caller must hold the auth lock."""
        url = f"https://{self._host}/app/v2/ha/oauth/get_token"
        payload = {
            "client_id": int(CLIENT_ID),
            "redirect_uri": OAUTH_REDIRECT_URL,
            "refresh_token": self.auth["refresh_token"],
        }
        try:
            async with self._session.get(
                url,
                params={"data": json.dumps(payload, separators=(",", ":"))},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
            ) as response:
                status = response.status
                body = await response.json(content_type=None)
        except TimeoutError as err:
            raise X20MaxCloudError(
                "Odświeżenie OAuth Xiaomi: przekroczono czas oczekiwania"
            ) from err
        except (aiohttp.ClientError, ValueError) as err:
            # Never include str(err): aiohttp response errors carry the full
            # request URL, which contains the refresh token.
            raise X20MaxCloudError(
                "Odświeżenie OAuth Xiaomi nie powiodło się "
                f"({type(err).__name__})"
            ) from err
        if status not in (200, 400, 401, 403):
            # Server errors, rate limiting and similar are transient; only
            # an explicit refusal means the grant itself is no longer valid.
            raise X20MaxCloudError(
                f"Odświeżenie OAuth Xiaomi: HTTP {status}"
            )
        if status == 200 and not isinstance(body, dict):
            raise X20MaxCloudError(
                "Odświeżenie OAuth Xiaomi: nieprawidłowa odpowiedź"
            )
        result = body.get("result") if isinstance(body, dict) else None
        if (
            status != 200
            or not isinstance(body, dict)
            or body.get("code") != 0
            or not isinstance(result, dict)
            or not result.get("access_token")
        ):
            raise X20MaxAuthError("Xiaomi odrzuciło odświeżenie danych OAuth")
        self.auth.update(result)
        self.auth["expires_ts"] = int(
            time.time()
            + int(result.get("expires_in") or 0) * TOKEN_EXPIRES_RATIO
        )
        await self._async_save()

    async def _async_post(
        self, path: str, data: dict[str, Any], *, retry_auth: bool = True
    ) -> dict[str, Any]:
        await self._async_ensure_token()
        try:
            async with self._session.post(
                f"https://{self._host}{path}",
                json=data,
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                status = response.status
                body = await response.json(content_type=None)
        except TimeoutError as err:
            raise X20MaxCloudError(
                "Xiaomi Cloud: przekroczono czas oczekiwania"
            ) from err
        except (aiohttp.ClientError, ValueError) as err:
            raise X20MaxCloudError(
                f"Błąd połączenia z Xiaomi Cloud ({type(err).__name__})"
            ) from err
        if status == 401 and retry_auth:
            await self._async_ensure_token(force=True)
            return await self._async_post(path, data, retry_auth=False)
        if status != 200:
            raise X20MaxCloudError(f"Xiaomi Cloud zwróciło HTTP {status}")
        if not isinstance(body, dict) or body.get("code") != 0:
            message = body.get("message", "nieznany błąd") if isinstance(
                body, dict
            ) else "nieprawidłowa odpowiedź"
            raise X20MaxCloudError(f"Xiaomi Cloud: {message}")
        return body

    async def async_get_properties(
        self, did: str, refs: tuple[PropertyRef, ...]
    ) -> dict[PropertyRef, Any]:
        params = [
            {"did": did, "siid": ref.siid, "piid": ref.piid} for ref in refs
        ]
        body = await self._async_post(
            "/app/v2/miotspec/prop/get",
            {"datasource": 1, "params": params},
        )
        values: dict[PropertyRef, Any] = {}
        for item in body.get("result") or []:
            if not isinstance(item, dict):
                continue
            if item.get("code", 0) != 0 or "value" not in item:
                continue
            values[PropertyRef(int(item["siid"]), int(item["piid"]))] = item[
                "value"
            ]
        return values

    async def async_set_property(
        self, did: str, ref: PropertyRef, value: Any
    ) -> None:
        body = await self._async_post(
            "/app/v2/miotspec/prop/set",
            {
                "params": [
                    {
                        "did": did,
                        "siid": ref.siid,
                        "piid": ref.piid,
                        "value": value,
                    }
                ]
            },
        )
        result = (body.get("result") or [{}])[0]
        if result.get("code", 0) != 0:
            raise X20MaxCloudError(
                f"MIoT {ref.siid}.{ref.piid}: kod {result.get('code')}"
            )

    async def async_action(
        self,
        did: str,
        siid: int,
        aiid: int,
        inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run a MIoT action; any non-zero result code raises.

        Callers that know how to verify an ambiguous result code (room
        cleaning) catch X20MaxActionError and check the robot state.
        """
        body = await self._async_post(
            "/app/v2/miotspec/action",
            {
                "params": {
                    "did": did,
                    "siid": siid,
                    "aiid": aiid,
                    "in": [item["value"] for item in inputs],
                }
            },
        )
        result = body.get("result") or {}
        code = result.get("code", 0)
        if code != 0:
            raise X20MaxActionError(siid, aiid, code)
        return result

    async def _async_device_list(self, dids: list[str]) -> list[dict[str, Any]]:
        body = await self._async_post(
            "/app/v2/home/device_list_page",
            {
                "limit": 200,
                "get_split_device": True,
                "get_third_device": True,
                "dids": dids,
            },
        )
        return [
            device
            for device in (body.get("result") or {}).get("list", [])
            if isinstance(device, dict)
        ]

    async def async_get_online(self, did: str) -> bool | None:
        """Return Xiaomi's online flag for one device, None when not listed.

        Xiaomi Home uses the same ``isOnline`` field of the device list for
        its device availability.
        """
        for device in await self._async_device_list([did]):
            if str(device.get("did")) == did and "isOnline" in device:
                return bool(device["isOnline"])
        return None

    async def async_list_robots(self) -> list[dict[str, Any]]:
        """Return only Xiaomi Robot Vacuum X20 Max devices."""
        homes = await self._async_post(
            "/app/v2/homeroom/gethome",
            {
                "limit": 150,
                "fetch_share": True,
                "fetch_share_dev": True,
                "plat_form": 0,
                "app_ver": 9,
            },
        )
        dids: set[str] = set()
        for key in ("homelist", "share_home_list"):
            for home in (homes.get("result") or {}).get(key, []):
                dids.update(str(did) for did in home.get("dids", []))
                for room in home.get("roomlist", []):
                    dids.update(str(did) for did in room.get("dids", []))
        robots: list[dict[str, Any]] = []
        ordered = sorted(dids)
        for index in range(0, len(ordered), 150):
            for device in await self._async_device_list(
                ordered[index : index + 150]
            ):
                if device.get("model") != MODEL:
                    continue
                robots.append(
                    {
                        "did": str(device["did"]),
                        "name": str(device.get("name") or "X20 Max"),
                        "model": MODEL,
                        "firmware": (device.get("extra") or {}).get(
                            "fw_version"
                        ),
                        "online": bool(device.get("isOnline", True)),
                    }
                )
        return robots
