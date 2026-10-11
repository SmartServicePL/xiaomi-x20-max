"""Ładowanie wpisu, błędy startu, odpytywanie chmury i dostępność."""

from __future__ import annotations

import logging

import pytest

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState

from custom_components.xiaomi_x20_max import controller as controller_module
from custom_components.xiaomi_x20_max.cloud import X20MaxAuthError, X20MaxCloudError
from custom_components.xiaomi_x20_max.const import DOMAIN

from .conftest import VACUUM, controller_of


async def test_setup_and_unload(hass, loaded) -> None:
    assert loaded.state is ConfigEntryState.LOADED
    assert hass.states.get(VACUUM).state == "docked"
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await hass.async_block_till_done()
    assert loaded.state is ConfigEntryState.NOT_LOADED
    assert loaded.entry_id not in hass.data[DOMAIN]


async def test_network_error_retries_setup(hass, cloud, entry) -> None:
    cloud.get_error = X20MaxCloudError("brak sieci")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_grant_asks_for_reauthentication(hass, cloud, entry) -> None:
    cloud.get_error = X20MaxAuthError("odrzucono")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_other_model_is_not_loaded(hass, cloud, entry) -> None:
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "model": "xiaomi.vacuum.other"}
    )
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_failed_poll_backs_off_without_log_spam(
    hass, cloud, loaded, fast_clock, caplog
) -> None:
    controller = controller_of(hass, loaded)
    cloud.get_error = X20MaxCloudError("Xiaomi Cloud: przekroczono czas")
    caplog.set_level(logging.DEBUG)
    caplog.clear()

    await controller._async_safe_refresh()  # nie rzuca wyjątku
    started: list[object] = []
    controller._start_refresh_task = lambda: started.append(1)

    fast_clock.now += 30
    controller._scheduled_refresh()
    assert len(started) == 1  # pierwsza ponowna próba po 30 s

    await controller._async_safe_refresh()  # druga porażka: 60 s przerwy
    fast_clock.now += 30
    controller._scheduled_refresh()
    assert len(started) == 1
    fast_clock.now += 30
    controller._scheduled_refresh()
    assert len(started) == 2

    for _ in range(10):
        await controller._async_safe_refresh()
    assert (
        controller._retry_at - fast_clock.now
        <= controller_module.MAX_BACKOFF_SECONDS
    )
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1

    cloud.get_error = None
    await controller.async_refresh()
    assert controller._failures == 0
    assert any("responding again" in r.getMessage() for r in caplog.records)


async def test_unavailable_after_grace_period(hass, cloud, loaded, fast_clock) -> None:
    controller = controller_of(hass, loaded)
    await controller.async_refresh()
    assert controller.available
    cloud.get_error = X20MaxCloudError("brak sieci")
    fast_clock.now += controller_module.AVAILABLE_GRACE_SECONDS + 1
    await controller._async_safe_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).state == "unavailable"


async def test_offline_robot_is_unavailable(hass, cloud, loaded, fast_clock) -> None:
    controller = controller_of(hass, loaded)
    controller._online_checked = 0.0  # wpis wczytany przed podmianą zegara
    await controller.async_refresh()
    cloud.online = False
    fast_clock.now += controller_module.ONLINE_CHECK_SECONDS
    await controller.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).state == "unavailable"

    fast_clock.now += 30
    cloud.online = True
    await controller.async_refresh()  # sprawdzane przy każdym odczycie
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).state == "docked"


async def test_unknown_online_flag_keeps_robot_available(
    hass, cloud, loaded, fast_clock
) -> None:
    controller = controller_of(hass, loaded)
    controller._online_checked = 0.0
    cloud.online = None
    fast_clock.now += controller_module.ONLINE_CHECK_SECONDS
    await controller.async_refresh()
    assert controller.available


async def test_rejected_grant_while_running_starts_reauth(
    hass, cloud, loaded
) -> None:
    cloud.get_error = X20MaxAuthError("odrzucono")
    with pytest.raises(controller_module.X20MaxAuthFailed):
        await controller_of(hass, loaded).async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_empty_answer_is_a_failure(hass, cloud, loaded) -> None:
    cloud.values = {}
    with pytest.raises(controller_module.X20MaxError):
        await controller_of(hass, loaded).async_refresh()
