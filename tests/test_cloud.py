"""Klient chmury: odświeżanie OAuth, przejęcie grantu Xiaomi Home, błędy."""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.xiaomi_x20_max import cloud as cloud_module
from custom_components.xiaomi_x20_max.cloud import (
    X20MaxActionError,
    X20MaxAuthError,
    X20MaxCloud,
    X20MaxCloudError,
    _load_bootstrap_auth,
)
from custom_components.xiaomi_x20_max.const import PropertyRef

SECRET = "REFRESH-SECRET-123"
TOKEN_URL = re.compile(r"/app/v2/ha/oauth/get_token")
FAR_FUTURE = 9_999_999_999


class Replies:
    """Kolejne odpowiedzi jednego adresu (status i JSON albo wyjątek)."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.urls: list[URL] = []
        self.bodies: list[object] = []

    async def __call__(self, method, url, data):
        self.urls.append(url)
        self.bodies.append(data)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            return AiohttpClientMockResponse(method, url, exc=reply)
        status, body = reply
        return AiohttpClientMockResponse(method, url, status=status, json=body)

    def refresh_tokens(self) -> list[str]:
        return [
            json.loads(url.query["data"])["refresh_token"] for url in self.urls
        ]


def ok_token(access="new-access", refresh="new-refresh"):
    return (
        200,
        {
            "code": 0,
            "result": {
                "access_token": access,
                "refresh_token": refresh,
                "expires_in": 3600,
            },
        },
    )


def make_cloud(hass, expires_ts=0) -> X20MaxCloud:
    client = X20MaxCloud(hass)
    client.auth = {
        "access_token": "old-access",
        "refresh_token": SECRET,
        "expires_ts": expires_ts,
    }
    return client


def bootstrap(value):
    return patch.object(cloud_module, "_load_bootstrap_auth", return_value=value)


async def test_refresh_is_saved(hass, aioclient_mock, hass_storage) -> None:
    replies = Replies(ok_token())
    aioclient_mock.get(TOKEN_URL, side_effect=replies)
    client = make_cloud(hass)
    await client._async_ensure_token()
    await hass.async_block_till_done()
    assert client.auth["access_token"] == "new-access"
    saved = hass_storage[cloud_module.STORE_KEY]["data"]
    assert saved["auth"]["refresh_token"] == "new-refresh"


async def test_error_text_never_contains_refresh_token(
    hass, aioclient_mock
) -> None:
    url = URL(f"https://de.ha.api.io.mi.com/x?data={SECRET}")
    info = aiohttp.RequestInfo(url, "GET", {}, url)
    error = aiohttp.TooManyRedirects(info, ())
    assert SECRET in str(error)  # ryzyko jest prawdziwe
    aioclient_mock.get(TOKEN_URL, side_effect=Replies(error))
    with pytest.raises(X20MaxCloudError) as err:
        await make_cloud(hass)._async_ensure_token()
    assert not isinstance(err.value, X20MaxAuthError)  # błąd chwilowy
    assert SECRET not in str(err.value)
    assert "TooManyRedirects" in str(err.value)


async def test_timeout_has_a_readable_text(hass, aioclient_mock) -> None:
    aioclient_mock.get(TOKEN_URL, side_effect=Replies(TimeoutError()))
    with pytest.raises(X20MaxCloudError) as err:
        await make_cloud(hass)._async_ensure_token()
    assert "przekroczono czas" in str(err.value)


async def test_server_error_and_bad_body_are_transient(
    hass, aioclient_mock
) -> None:
    aioclient_mock.get(
        TOKEN_URL, side_effect=Replies((503, {}), (200, ["nie", "słownik"]))
    )
    client = make_cloud(hass)
    for _ in range(2):
        with pytest.raises(X20MaxCloudError) as err:
            await client._async_ensure_token()
        assert not isinstance(err.value, X20MaxAuthError)


async def test_rejection_without_new_grant_is_auth_error(
    hass, aioclient_mock
) -> None:
    replies = Replies((200, {"code": -1, "message": "invalid"}))
    aioclient_mock.get(TOKEN_URL, side_effect=replies)
    with (
        bootstrap(("de", {"access_token": "a", "refresh_token": SECRET})),
        pytest.raises(X20MaxAuthError),
    ):
        await make_cloud(hass)._async_ensure_token()
    assert len(replies.urls) == 1  # ten sam grant nie jest ponawiany


async def test_rejection_adopts_newer_xiaomi_home_grant(
    hass, aioclient_mock
) -> None:
    replies = Replies((401, {"code": 401}), ok_token("fresh", "fresh-refresh"))
    aioclient_mock.get(TOKEN_URL, side_effect=replies)
    newer = {"access_token": "home", "refresh_token": "home-refresh", "expires_ts": 0}
    client = make_cloud(hass)
    with bootstrap(("de", newer)):
        await client._async_ensure_token()
    assert replies.refresh_tokens() == [SECRET, "home-refresh"]
    assert client.auth["access_token"] == "fresh"


async def test_rejection_adopts_valid_xiaomi_home_token_without_refresh(
    hass, aioclient_mock
) -> None:
    replies = Replies((200, {"code": -1}))
    aioclient_mock.get(TOKEN_URL, side_effect=replies)
    valid = {
        "access_token": "home",
        "refresh_token": "home-refresh",
        "expires_ts": FAR_FUTURE,
    }
    client = make_cloud(hass)
    with bootstrap(("de", valid)):
        await client._async_ensure_token()
    assert client.auth["access_token"] == "home"
    assert len(replies.urls) == 1


async def test_reimport_forces_the_xiaomi_home_grant(hass) -> None:
    grant = {"access_token": "a", "refresh_token": SECRET, "expires_ts": FAR_FUTURE}
    client = make_cloud(hass, FAR_FUTURE)
    with bootstrap(("pl", grant)):
        await client.async_reimport()
    assert client.server == "pl"
    with bootstrap(None), pytest.raises(X20MaxAuthError):
        await client.async_reimport()


async def test_initialize_without_any_grant(hass, hass_storage) -> None:
    client = X20MaxCloud(hass)
    with bootstrap(None), pytest.raises(X20MaxAuthError):
        await client.async_initialize()


async def test_initialize_uses_the_private_store(hass, hass_storage) -> None:
    hass_storage[cloud_module.STORE_KEY] = {
        "version": 1,
        "key": cloud_module.STORE_KEY,
        "data": {
            "server": "pl",
            "auth": {
                "access_token": "a",
                "refresh_token": "r",
                "expires_ts": FAR_FUTURE,
            },
        },
    }
    client = X20MaxCloud(hass)
    with bootstrap(None):
        await client.async_initialize()
    assert client.ready
    assert client.server == "pl"


async def test_action_code_is_raised(hass, aioclient_mock) -> None:
    aioclient_mock.post(
        re.compile("/miotspec/action"),
        json={"code": 0, "result": {"code": -704083036}},
    )
    client = make_cloud(hass, FAR_FUTURE)
    with pytest.raises(X20MaxActionError) as err:
        await client.async_action("1", 2, 16, [{"piid": 15, "value": "[10]"}])
    assert err.value.code == -704083036
    assert str(err.value) == "Akcja MIoT 2.16: kod -704083036"
    _, _, body, headers = aioclient_mock.mock_calls[-1]
    assert body == {"params": {"did": "1", "siid": 2, "aiid": 16, "in": ["[10]"]}}
    assert headers["Authorization"] == "Bearerold-access"


async def test_get_properties_skips_bad_items(hass, aioclient_mock) -> None:
    aioclient_mock.post(
        re.compile("/miotspec/prop/get"),
        json={
            "code": 0,
            "result": [
                "x",
                {"siid": 2, "piid": 2, "code": 0, "value": 4},
                {"siid": 2, "piid": 16, "code": -1},
            ],
        },
    )
    values = await make_cloud(hass, FAR_FUTURE).async_get_properties(
        "1", (PropertyRef(2, 2), PropertyRef(2, 16))
    )
    assert values == {PropertyRef(2, 2): 4}


async def test_expired_access_token_is_refreshed_once(
    hass, aioclient_mock
) -> None:
    calls = Replies((401, {}), (200, {"code": 0, "result": []}))
    aioclient_mock.post(re.compile("/miotspec/prop/get"), side_effect=calls)
    aioclient_mock.get(TOKEN_URL, side_effect=Replies(ok_token()))
    client = make_cloud(hass, FAR_FUTURE)
    assert await client.async_get_properties("1", ()) == {}
    assert len(calls.urls) == 2
    assert client.auth["access_token"] == "new-access"


async def test_online_flag(hass, aioclient_mock) -> None:
    replies = Replies(
        (200, {"code": 0, "result": {"list": [{"did": "7", "isOnline": False}]}}),
        (200, {"code": 0, "result": {"list": []}}),
    )
    aioclient_mock.post(re.compile("/home/device_list_page"), side_effect=replies)
    client = make_cloud(hass, FAR_FUTURE)
    assert await client.async_get_online("7") is False
    assert await client.async_get_online("7") is None
    assert replies.bodies[0]["dids"] == ["7"]


async def test_list_robots_only_x20_max(hass, aioclient_mock) -> None:
    aioclient_mock.post(
        re.compile("/homeroom/gethome"),
        json={
            "code": 0,
            "result": {
                "homelist": [
                    {"dids": ["1"], "roomlist": [{"dids": ["2"]}]},
                ]
            },
        },
    )
    aioclient_mock.post(
        re.compile("/home/device_list_page"),
        json={
            "code": 0,
            "result": {
                "list": [
                    {
                        "did": "1",
                        "name": "Stefan",
                        "model": "xiaomi.vacuum.d109gl",
                        "extra": {"fw_version": "4.5.6_0406"},
                    },
                    {"did": "2", "name": "Lampa", "model": "yeelink.light.x"},
                ]
            },
        },
    )
    robots = await make_cloud(hass, FAR_FUTURE).async_list_robots()
    assert robots == [
        {
            "did": "1",
            "name": "Stefan",
            "model": "xiaomi.vacuum.d109gl",
            "firmware": "4.5.6_0406",
            "online": True,
        }
    ]


async def test_connection_error_text(hass, aioclient_mock) -> None:
    aioclient_mock.post(
        re.compile("/miotspec/prop/get"),
        exc=aiohttp.ClientConnectionError("boom"),
    )
    with pytest.raises(X20MaxCloudError) as err:
        await make_cloud(hass, FAR_FUTURE).async_get_properties("1", ())
    assert str(err.value) == "Błąd połączenia z Xiaomi Cloud (ClientConnectionError)"


def test_bootstrap_reads_xiaomi_home_storage(tmp_path) -> None:
    folder = tmp_path / ".storage" / "xiaomi_home" / "miot_config"
    folder.mkdir(parents=True)
    grant = {"auth_info": {"access_token": "a", "refresh_token": "r"}}
    # Xiaomi Home dopisuje 32 bajty sumy kontrolnej za JSON-em.
    (folder / "123_de.dict").write_bytes(json.dumps(grant).encode() + b"\x00" * 32)
    (folder / "456_pl.dict").write_bytes(b"uszkodzony")
    assert _load_bootstrap_auth(str(tmp_path)) == (
        "de",
        {"access_token": "a", "refresh_token": "r"},
    )


def test_bootstrap_without_xiaomi_home(tmp_path) -> None:
    assert _load_bootstrap_auth(str(tmp_path)) is None
