"""Usługi integracji: sprzątanie pokoi, potwierdzanie startu, akcje surowe."""

from __future__ import annotations

import json

import pytest

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.xiaomi_x20_max import controller as controller_module
from custom_components.xiaomi_x20_max.const import DOMAIN, PropertyRef

from .conftest import DID, VACUUM, controller_of

STATUS = PropertyRef(2, 2)
TASK = PropertyRef(2, 40)
FAULTS = PropertyRef(2, 66)
MAP = PropertyRef(2, 16)
UNCONFIRMED = controller_module.ROOM_CLEAN_UNCONFIRMED_CODE


async def clean_rooms(hass, rooms, **options) -> None:
    await hass.services.async_call(
        DOMAIN,
        "clean_rooms",
        {"entity_id": VACUUM, "rooms": rooms, **options},
        blocking=True,
    )


def confirm_reads(cloud) -> int:
    return sum(
        1
        for refs in cloud.reads
        if refs == controller_module.START_CONFIRM_PROPERTIES
    )


async def test_rooms_by_id_and_name_keep_order(hass, cloud, loaded) -> None:
    await clean_rooms(hass, [12, "kuchnia ", "12", 14])
    assert cloud.actions == [(DID, 2, 16, ["[12,13,14]"])]


async def test_settings_are_written_before_start(hass, cloud, loaded) -> None:
    await clean_rooms(
        hass,
        [12],
        mode="vacuum_and_mop",
        suction="turbo",
        water_level="high",
        passes=1,
        route="daily",
    )
    assert [(ref.siid, ref.piid, value) for _, ref, value in cloud.writes] == [
        (2, 4, 3),
        (2, 9, 4),
        (2, 10, 3),
        (2, 8, 1),
        (2, 74, 2),
    ]
    assert cloud.actions == [(DID, 2, 16, ["[12]"])]


async def test_code_zero_needs_no_confirmation(hass, cloud, loaded) -> None:
    await clean_rooms(hass, [13])
    assert confirm_reads(cloud) == 1  # tylko odczyt bazowy


@pytest.mark.parametrize(
    ("rooms", "key", "placeholders"),
    [
        ([99], "unknown_room_id", {"room_id": "99"}),
        (["Strych"], "unknown_room_name", {"room_name": "Strych"}),
    ],
)
async def test_unknown_room_is_a_validation_error(
    hass, cloud, loaded, rooms, key, placeholders
) -> None:
    with pytest.raises(ServiceValidationError) as info:
        await clean_rooms(hass, rooms)
    assert info.value.translation_key == key
    assert info.value.translation_placeholders == placeholders
    assert cloud.actions == []


async def test_empty_room_list_is_rejected(hass, cloud, loaded) -> None:
    with pytest.raises(ServiceValidationError) as info:
        await controller_of(hass, loaded).async_clean_rooms([])
    assert info.value.translation_key == "no_rooms"


async def test_missing_map_is_read_again_then_rejected(
    hass, cloud, loaded
) -> None:
    controller_of(hass, loaded)._values.pop(MAP)
    cloud.values[DID][MAP] = json.dumps({"rooms": []})
    with pytest.raises(HomeAssistantError) as info:
        await clean_rooms(hass, [12])
    assert info.value.translation_key == "room_map_unavailable"
    assert (MAP,) in cloud.reads
    assert cloud.actions == []


async def test_map_loaded_on_demand_is_used(hass, cloud, loaded) -> None:
    controller_of(hass, loaded)._values.pop(MAP)
    await clean_rooms(hass, ["Korytarz"])
    assert cloud.actions == [(DID, 2, 16, ["[14]"])]


async def test_unconfirmed_code_accepted_when_robot_starts(
    hass, cloud, loaded, fast_clock
) -> None:
    cloud.action_code = UNCONFIRMED
    cloud.confirm_snapshots = [
        {STATUS: 2, TASK: "", FAULTS: '{"fault":[0]}'},  # odczyt bazowy
        {STATUS: 2},
        {STATUS: 4},
    ]
    await clean_rooms(hass, [12, 13])
    assert cloud.confirm_snapshots == []


async def test_unconfirmed_code_accepted_when_task_lists_rooms(
    hass, cloud, loaded, fast_clock
) -> None:
    """Przed sprzątaniem robot myje mopy (7), a zadanie ma już nowe pokoje."""
    cloud.action_code = UNCONFIRMED
    cloud.confirm_snapshots = [
        {STATUS: 2, TASK: json.dumps({"rooms": [14]})},
        {STATUS: 7, TASK: json.dumps({"rooms": [12, 13]})},
    ]
    await clean_rooms(hass, [12, 13])
    assert cloud.confirm_snapshots == []


async def test_unconfirmed_code_raises_when_robot_stays_docked(
    hass, cloud, loaded, fast_clock
) -> None:
    cloud.action_code = UNCONFIRMED
    stale = json.dumps({"rooms": [12, 13]})  # zadanie z poprzedniego dnia
    snapshot = {STATUS: 2, TASK: stale, FAULTS: '{"fault":[210030]}'}
    cloud.confirm_snapshots = [dict(snapshot) for _ in range(200)]
    with pytest.raises(HomeAssistantError) as info:
        await clean_rooms(hass, [12, 13])
    err = info.value
    assert not isinstance(err, ServiceValidationError)
    assert err.translation_key == "room_clean_not_started"
    assert err.translation_placeholders == {
        "rooms": "Przedsionek (12), Kuchnia (13)",
        "status": "2",
        "faults": "210030",
    }
    expected = 1 + (
        controller_module.START_CONFIRM_TIMEOUT
        // controller_module.START_CONFIRM_INTERVAL
    )
    assert confirm_reads(cloud) == expected


async def test_mop_wash_before_leaving_is_waited_for(
    hass, cloud, loaded, fast_clock
) -> None:
    """Powtórny start tych samych pokoi: 2.40 się nie zmienia, robot przez
    ok. 3 min myje mopy w stacji (7), dopiero potem rusza (4)."""
    cloud.action_code = UNCONFIRMED
    same = json.dumps({"rooms": [12, 13]})
    cloud.confirm_snapshots = (
        [{STATUS: 2, TASK: same}]
        + [{STATUS: 7, TASK: same} for _ in range(60)]
        + [{STATUS: 4, TASK: same}]
    )
    await clean_rooms(hass, [12, 13])
    assert cloud.confirm_snapshots == []


async def test_refusal_with_fault_fails_at_once(
    hass, cloud, loaded, fast_clock
) -> None:
    """Brak czystej wody: robot staje w pauzie z kodem usterki."""
    cloud.action_code = UNCONFIRMED
    cloud.confirm_snapshots = [
        {STATUS: 2, TASK: "", FAULTS: '{"fault":[0]}'},
        {STATUS: 5, FAULTS: '{"fault":[210030]}'},
    ] + [{STATUS: 5, FAULTS: '{"fault":[210030]}'} for _ in range(10)]
    with pytest.raises(HomeAssistantError) as info:
        await clean_rooms(hass, [13])
    assert info.value.translation_placeholders["status"] == "5"
    assert confirm_reads(cloud) == 2


async def test_robot_paused_before_the_call_gets_time_to_start(
    hass, cloud, loaded, fast_clock
) -> None:
    """Robot stał w pauzie z usterką (historia: 06.10, 210014): pierwsze
    odczyty po poleceniu pokazują jeszcze starą pauzę."""
    cloud.action_code = UNCONFIRMED
    paused = {STATUS: 5, TASK: "", FAULTS: '{"fault":[210014]}'}
    cloud.confirm_snapshots = [dict(paused) for _ in range(4)] + [
        {STATUS: 4, TASK: "", FAULTS: '{"fault":[0]}'}
    ]
    await clean_rooms(hass, [13])
    assert cloud.confirm_snapshots == []


async def test_busy_robot_is_not_a_start(hass, cloud, loaded, fast_clock) -> None:
    cloud.action_code = UNCONFIRMED
    other = json.dumps({"rooms": [14]})
    cloud.confirm_snapshots = [{STATUS: 4, TASK: other} for _ in range(200)]
    with pytest.raises(HomeAssistantError) as info:
        await clean_rooms(hass, [12])
    assert info.value.translation_key == "room_clean_not_started"


async def test_error_status_stops_waiting(
    hass, cloud, loaded, fast_clock
) -> None:
    cloud.action_code = UNCONFIRMED
    cloud.confirm_snapshots = [
        {STATUS: 2},
        {STATUS: 15, FAULTS: '{"fault":[210014]}'},
    ]
    with pytest.raises(HomeAssistantError) as info:
        await clean_rooms(hass, [13])
    assert info.value.translation_placeholders["status"] == "15"
    assert info.value.translation_placeholders["faults"] == "210014"
    assert cloud.confirm_snapshots == []


async def test_other_action_code_is_an_error(hass, cloud, loaded) -> None:
    cloud.action_code = -1
    with pytest.raises(HomeAssistantError) as info:
        await clean_rooms(hass, [13])
    assert str(info.value) == "Akcja MIoT 2.16 nie powiodła się: kod -1"


async def test_raw_room_action_is_not_confirmed(hass, cloud, loaded) -> None:
    cloud.action_code = UNCONFIRMED
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "execute_action",
            {"entity_id": VACUUM, "siid": 2, "aiid": 16},
            blocking=True,
        )


async def test_station_action(hass, cloud, loaded) -> None:
    await hass.services.async_call(
        DOMAIN,
        "station_action",
        {"entity_id": VACUUM, "action": "wash_mops"},
        blocking=True,
    )
    assert cloud.actions == [(DID, 2, 19, [])]


async def test_set_property_and_execute_action(hass, cloud, loaded) -> None:
    await hass.services.async_call(
        DOMAIN,
        "set_property",
        {"entity_id": VACUUM, "siid": 2, "piid": 74, "value": 2},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "execute_action",
        {
            "entity_id": VACUUM,
            "siid": 2,
            "aiid": 16,
            "inputs": [{"piid": 15, "value": "[12]"}],
        },
        blocking=True,
    )
    assert cloud.writes == [(DID, PropertyRef(2, 74), 2)]
    assert cloud.actions == [(DID, 2, 16, ["[12]"])]


async def test_set_dnd(hass, cloud, loaded) -> None:
    await hass.services.async_call(
        DOMAIN,
        "set_dnd",
        {"entity_id": VACUUM, "start": "22:00:00", "end": "07:30:00"},
        blocking=True,
    )
    packed = (22 << 24) | (7 << 8) | 30
    assert cloud.writes == [
        (DID, PropertyRef(11, 2), packed),
        (DID, PropertyRef(11, 1), True),
    ]
    assert controller_of(hass, loaded).decode_dnd() == {
        "start": "22:00",
        "end": "07:30",
    }


async def test_entity_of_another_integration_is_rejected(
    hass, cloud, loaded
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "station_action",
            {"entity_id": "vacuum.inny", "action": "wash_mops"},
            blocking=True,
        )
