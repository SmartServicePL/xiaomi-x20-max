"""Dodawanie robota i ponowne logowanie (grant Xiaomi Home)."""

from __future__ import annotations

import pytest

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xiaomi_x20_max.cloud import X20MaxAuthError, X20MaxCloudError
from custom_components.xiaomi_x20_max.const import CONF_DID, DOMAIN, MODEL

from .conftest import DID


async def test_user_flow_creates_entry(hass, cloud) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DID: DID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Stefan X20 Max"
    assert result["data"] == {
        "did": DID,
        "name": "Stefan",
        "model": MODEL,
        "firmware": "4.5.6_0406",
    }
    assert result["result"].unique_id == DID


async def test_user_flow_without_grant(hass, cloud) -> None:
    cloud.ready = False

    async def fail() -> None:
        raise X20MaxAuthError("brak")

    cloud.async_initialize = fail
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_auth"


async def test_user_flow_without_robots(hass, cloud) -> None:
    cloud.robots = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices"


async def test_robot_added_only_once(hass, cloud, entry) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DID: DID}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_succeeds_and_reloads_other_robots(
    hass, cloud, loaded
) -> None:
    other = MockConfigEntry(
        domain=DOMAIN,
        title="Franek X20 Max",
        unique_id="987654321",
        version=2,
        data={"did": "987654321", "name": "Franek", "model": MODEL},
    )
    other.add_to_hass(hass)
    cloud.values["987654321"] = {}  # brak odpowiedzi: wpis czeka na ponowienie
    await hass.config_entries.async_setup(other.entry_id)
    assert other.state is ConfigEntryState.SETUP_RETRY

    reloads: list[str] = []
    hass.config_entries.async_schedule_reload = reloads.append
    result = await loaded.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert other.entry_id in reloads


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"reimport_error": X20MaxAuthError("x")}, "reauth_failed"),
        ({"reimport_error": X20MaxCloudError("x")}, "cannot_connect"),
        ({"robots": []}, "robot_not_found"),
    ],
)
async def test_reauth_errors(hass, cloud, loaded, change, error) -> None:
    for key, value in change.items():
        setattr(cloud, key, value)
    result = await loaded.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
