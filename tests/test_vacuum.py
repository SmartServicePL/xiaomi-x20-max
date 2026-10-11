"""Encja odkurzacza: stany z tabeli statusów, polecenia, segmenty."""

from __future__ import annotations

import json

import pytest

from homeassistant.components.vacuum import VacuumActivity

from custom_components.xiaomi_x20_max.const import STATUSES, PropertyRef

from .conftest import DID, VACUUM, controller_of

STATUS = PropertyRef(2, 2)
CHARGING = PropertyRef(3, 2)
TASK = PropertyRef(2, 40)


async def set_values(hass, cloud, loaded, **changes) -> None:
    """Zmienia odczyt z chmury i odświeża stan jak cykliczne odpytywanie."""
    values = cloud.values[DID]
    for key, value in changes.items():
        values[{"status": STATUS, "charging": CHARGING, "task": TASK}[key]] = value
    await controller_of(hass, loaded).async_refresh()
    await hass.async_block_till_done()


async def test_docked_robot(hass, loaded) -> None:
    state = hass.states.get(VACUUM)
    assert state.state == VacuumActivity.DOCKED
    assert state.attributes["room_ids"] == [12, 13, 14]
    assert state.attributes["rooms_by_id"] == {
        "12": "Przedsionek",
        "13": "Kuchnia",
        "14": "Korytarz",
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (1, VacuumActivity.IDLE),
        (2, VacuumActivity.DOCKED),
        (4, VacuumActivity.CLEANING),
        (5, VacuumActivity.PAUSED),
        (6, VacuumActivity.RETURNING),
        (7, VacuumActivity.CLEANING),
        (14, VacuumActivity.DOCKED),
        (15, VacuumActivity.ERROR),
        (20, VacuumActivity.RETURNING),
    ],
)
async def test_status_to_state(hass, cloud, loaded, status, expected) -> None:
    await set_values(hass, cloud, loaded, status=status, charging=0)
    assert hass.states.get(VACUUM).state == expected


async def test_charging_in_station_is_docked(hass, cloud, loaded) -> None:
    await set_values(hass, cloud, loaded, status=1, charging=1)
    assert hass.states.get(VACUUM).state == VacuumActivity.DOCKED
    await set_values(hass, cloud, loaded, status=1, charging=0)
    assert hass.states.get(VACUUM).state == VacuumActivity.IDLE


async def test_unknown_status_has_no_state(hass, cloud, loaded) -> None:
    await set_values(hass, cloud, loaded, status=99, charging=0)
    assert hass.states.get(VACUUM).state == "unknown"


async def test_room_task_is_not_docked_until_the_station_takes_over(
    hass, cloud, loaded
) -> None:
    """Przebieg z historii robota: mycie mopów w trakcie zadania to nie koniec.

    7 → 4 → 20 → 7 → 4 → 6 → 7 → 14 (zapis z 11.10.2026). Automatyzacje,
    które czekają na „docked” jako koniec sprzątania, nie mogą go dostać
    przed suszeniem mopów (14).
    """
    task = json.dumps({"rooms": [12, 13, 14]})
    sequence = [
        (7, task, VacuumActivity.CLEANING),
        (4, task, VacuumActivity.CLEANING),
        (20, task, VacuumActivity.RETURNING),
        (7, task, VacuumActivity.CLEANING),
        (4, task, VacuumActivity.CLEANING),
        (6, "", VacuumActivity.RETURNING),
        (7, "", VacuumActivity.CLEANING),
        (14, "", VacuumActivity.DOCKED),
    ]
    for status, current_task, expected in sequence:
        await set_values(hass, cloud, loaded, status=status, task=current_task, charging=0)
        assert hass.states.get(VACUUM).state == expected, status


def test_status_table_covers_known_values() -> None:
    assert set(STATUSES) == set(range(1, 22))


@pytest.mark.parametrize(
    ("service", "data", "action"),
    [
        ("start", {}, (2, 1)),
        ("pause", {}, (2, 7)),
        ("stop", {}, (2, 2)),
        ("return_to_base", {}, (2, 3)),
        ("locate", {}, (6, 1)),
    ],
)
async def test_commands(hass, cloud, loaded, service, data, action) -> None:
    await hass.services.async_call(
        "vacuum", service, {"entity_id": VACUUM, **data}, blocking=True
    )
    assert cloud.actions[-1][1:3] == action


async def test_start_when_paused_resumes(hass, cloud, loaded) -> None:
    await set_values(hass, cloud, loaded, status=5, charging=0)
    await hass.services.async_call(
        "vacuum", "start", {"entity_id": VACUUM}, blocking=True
    )
    assert cloud.actions[-1][1:3] == (2, 8)


async def test_fan_speed(hass, cloud, loaded) -> None:
    await hass.services.async_call(
        "vacuum",
        "set_fan_speed",
        {"entity_id": VACUUM, "fan_speed": "turbo"},
        blocking=True,
    )
    assert cloud.writes[-1] == (DID, PropertyRef(2, 9), 4)


async def test_send_command_clean_rooms(hass, cloud, loaded) -> None:
    await hass.services.async_call(
        "vacuum",
        "send_command",
        {"entity_id": VACUUM, "command": "clean_rooms", "params": {"rooms": [13]}},
        blocking=True,
    )
    assert cloud.actions[-1] == (DID, 2, 16, ["[13]"])


async def test_segments(hass, loaded) -> None:
    entity = hass.data["entity_components"]["vacuum"].get_entity(VACUUM)
    segments = await entity.async_get_segments()
    assert [(segment.id, segment.name) for segment in segments] == [
        ("12", "Przedsionek"),
        ("13", "Kuchnia"),
        ("14", "Korytarz"),
    ]
