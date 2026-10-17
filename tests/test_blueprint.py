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
def language() -> str:
    """Język treści powiadomień (wejście blueprintu)."""
    return "pl"


@pytest.fixture
async def notifications(hass, tmp_path, language):
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
                        "language": language,
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
    assert notifications[0].data["title"] == "Sprzątanie: Problem ze stacją"
    assert notifications[0].data["message"] == (
        "Kody usterek: 210030\nSprawdź stację robota."
    )


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
    hass.states.async_set(STATION, "OK", {"problem": "Kody usterek: 320004"})
    hass.states.async_set(VACUUM, "error")
    await hass.async_block_till_done()
    assert len(notifications) == 1
    assert notifications[0].data["title"] == "Sprzątanie: Błąd robota"
    assert notifications[0].data["message"] == (
        "Robot zgłosił błąd. Kody usterek: 320004\nSprawdź robota i stację."
    )


async def test_unavailable_robot_after_two_minutes(hass, notifications) -> None:
    hass.states.async_set(VACUUM, "unavailable")
    await hass.async_block_till_done()
    await pass_time(hass, 3)
    assert len(notifications) == 1
    assert notifications[0].data["title"] == "Sprzątanie: Robot nie odpowiada"
    assert notifications[0].data["message"] == (
        "Robot nie odpowiada od 2 minut.\n"
        "Sprawdź, czy robot i stacja mają zasilanie oraz dostęp do sieci."
    )


async def test_consumable_below_threshold(hass, notifications) -> None:
    hass.states.async_set(MOPS, "18", {"remaining_hours": 12})
    await hass.async_block_till_done()
    assert len(notifications) == 1
    assert notifications[0].data["title"] == "Sprzątanie: Zużycie elementu"
    assert notifications[0].data["message"] == (
        "Mopy: pozostało 18 % — około 12 godz. pracy.\n"
        "Wyczyść lub wymień element, a potem wyzeruj jego licznik."
    )


async def test_detergent_without_hours(hass, notifications) -> None:
    hass.states.async_set("sensor.x20_detergent", "14")
    await hass.async_block_till_done()
    assert len(notifications) == 1
    assert notifications[0].data["title"] == "Sprzątanie: Mało detergentu"
    assert notifications[0].data["message"] == (
        "Pozostało 14 % detergentu.\nUzupełnij detergent w stacji."
    )


@pytest.mark.parametrize("language", ["en"])
async def test_english_texts(hass, notifications) -> None:
    hass.states.async_set(MOPS, "18", {"remaining_hours": 12})
    hass.states.async_set("sensor.x20_detergent", "14")
    await hass.async_block_till_done()
    assert [(n.data["title"], n.data["message"]) for n in notifications] == [
        (
            "Cleaning: Item wear",
            "Mops: 18 % left — about 12 operating hours.\n"
            "Clean or replace the item, then reset its counter.",
        ),
        (
            "Cleaning: Low detergent",
            "14 % of detergent left.\nRefill the detergent in the station.",
        ),
    ]


async def test_robot_name_is_available_to_actions(hass, tmp_path) -> None:
    """Nazwa robota nie jest w tytule; akcja może użyć x20_robot_name."""
    target = tmp_path / "blueprints" / "automation" / "SmartServicePL"
    target.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target / BLUEPRINT.name)
    hass.config.config_dir = str(tmp_path)
    calls = async_mock_service(hass, "test", "notify")
    hass.states.async_set(VACUUM, "docked")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"SmartServicePL/{BLUEPRINT.name}",
                    "input": {
                        "robot_name": "Franek",
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
                                "data": {"title": "{{ x20_robot_name }}"},
                            }
                        ],
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    hass.states.async_set(VACUUM, "error")
    await hass.async_block_till_done()
    assert calls[0].data["title"] == "Franek"
