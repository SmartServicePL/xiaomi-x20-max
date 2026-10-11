"""Blueprint powiadomień serwisowych na prawdziwym silniku automatyzacji."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import shutil

import pytest

from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints"
    / "automation"
    / "SmartServicePL"
    / "x20_max_maintenance.yaml"
)
STATION = "sensor.x20_station_alerts"
VACUUM = "vacuum.x20"
MOPS = "sensor.x20_mops"


@pytest.fixture
async def notifications(hass, tmp_path):
    """Automatyzacja z blueprintu; powiadomienie trafia do test.notify."""
    target = tmp_path / "blueprints" / "automation" / "SmartServicePL"
    target.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target / BLUEPRINT.name)
    hass.config.config_dir = str(tmp_path)
    calls = async_mock_service(hass, "test", "notify")

    hass.states.async_set(STATION, "OK", {"problem": None})
    hass.states.async_set(VACUUM, "docked")
    for name in ("detergent", "mops", "filter", "main_brush", "side_brush", "dust_bag"):
        hass.states.async_set(f"sensor.x20_{name}", "80")

    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"SmartServicePL/{BLUEPRINT.name}",
                    "input": {
                        "robot_name": "Stefan",
                        "language": "pl",
                        "vacuum": VACUUM,
                        "station_alert": STATION,
                        "detergent": "sensor.x20_detergent",
                        "mops": MOPS,
                        "filter": "sensor.x20_filter",
                        "main_brush": "sensor.x20_main_brush",
                        "side_brush": "sensor.x20_side_brush",
                        "dust_bag": "sensor.x20_dust_bag",
                        "notification_actions": [
                            {
                                "action": "test.notify",
                                "data": {
                                    "title": "{{ x20_title }}",
                                    "message": "{{ x20_message }}",
                                },
                            }
                        ],
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    return calls


async def pass_time(hass, minutes: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done()


async def test_station_problem_after_one_minute(hass, notifications) -> None:
    hass.states.async_set(STATION, "Problem", {"problem": "Kody usterek: 210030"})
    await hass.async_block_till_done()
    assert notifications == []
    await pass_time(hass, 2)
    assert len(notifications) == 1
    assert notifications[0].data["title"] == "X20 Max: Stefan"
    assert notifications[0].data["message"] == "Kody usterek: 210030"


async def test_problem_returning_after_cloud_outage_is_silent(
    hass, notifications
) -> None:
    hass.states.async_set(STATION, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(STATION, "Problem", {"problem": "Kody usterek: 210030"})
    await hass.async_block_till_done()
    await pass_time(hass, 2)
    assert notifications == []


async def test_vacuum_error(hass, notifications) -> None:
    hass.states.async_set(VACUUM, "error")
    await hass.async_block_till_done()
    assert len(notifications) == 1
    assert "Robot przeszedł w stan błędu." in notifications[0].data["message"]


async def test_unavailable_robot_after_two_minutes(hass, notifications) -> None:
    hass.states.async_set(VACUUM, "unavailable")
    await hass.async_block_till_done()
    await pass_time(hass, 3)
    assert len(notifications) == 1
    assert "nie odpowiada" in notifications[0].data["message"]


async def test_consumable_below_threshold(hass, notifications) -> None:
    hass.states.async_set(MOPS, "18", {"remaining_hours": 12})
    await hass.async_block_till_done()
    assert len(notifications) == 1
    message = notifications[0].data["message"]
    assert "Mopy: pozostało 18%" in message
    assert "(około 12 h pracy)" in message
    assert "wyzeruj jego licznik" in message
