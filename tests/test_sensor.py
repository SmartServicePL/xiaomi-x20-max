"""Sensory: usterki, alarmy stacji, pomieszczenia, aktualna lokalizacja."""

from __future__ import annotations

import json

import pytest

from custom_components.xiaomi_x20_max.const import PropertyRef

from .conftest import DID, controller_of

FAULTS = "sensor.stefan_x20_max_faults"
ALERTS = "sensor.stefan_x20_max_station_alerts"
ROOMS = "sensor.stefan_x20_max_rooms"
LOCATION = "sensor.stefan_x20_max_current_location"


async def refresh(hass, cloud, loaded, values: dict[PropertyRef, object]) -> None:
    cloud.values[DID].update(values)
    await controller_of(hass, loaded).async_refresh()
    await hass.async_block_till_done()


async def test_no_faults(hass, loaded) -> None:
    assert hass.states.get(FAULTS).state == "OK"
    alerts = hass.states.get(ALERTS)
    assert alerts.state == "OK"
    assert alerts.attributes["problem"] is None


async def test_known_fault_is_described(hass, cloud, loaded) -> None:
    await refresh(hass, cloud, loaded, {PropertyRef(2, 66): '{"fault":[0,210030]}'})
    assert hass.states.get(FAULTS).state == "210030: Clean water tank level is low"
    alerts = hass.states.get(ALERTS)
    assert alerts.state == "Problem"
    assert alerts.attributes["problem"] == (
        "Fault codes: 210030: Clean water tank level is low"
    )


async def test_fault_description_follows_language(hass, cloud, loaded) -> None:
    hass.config.language = "pl"
    await refresh(hass, cloud, loaded, {PropertyRef(2, 66): '{"fault":[210030]}'})
    assert hass.states.get(FAULTS).state == (
        "210030: Poziom wody w zbiorniku na czystą wodę jest niski"
    )


async def test_unknown_fault_shows_the_code(hass, cloud, loaded) -> None:
    await refresh(hass, cloud, loaded, {PropertyRef(2, 66): '{"fault":[210050]}'})
    assert hass.states.get(FAULTS).state == "210050"


async def test_malformed_faults_do_not_break_the_sensor(hass, cloud, loaded) -> None:
    raw = '{"fault":["abc", 210030]}'
    await refresh(hass, cloud, loaded, {PropertyRef(2, 66): raw})
    assert hass.states.get(FAULTS).state == raw
    assert controller_of(hass, loaded).active_fault_codes() == [210030]


async def test_water_check_failure_is_an_alert(hass, cloud, loaded) -> None:
    await refresh(hass, cloud, loaded, {PropertyRef(2, 54): 3})
    assert hass.states.get(ALERTS).attributes["alerts"] == [
        "Water system check failed"
    ]


async def test_rooms_sensor(hass, loaded) -> None:
    state = hass.states.get(ROOMS)
    assert state.state == "Przedsionek, Kuchnia, Korytarz"
    assert state.attributes["by_id"] == {
        "12": "Przedsionek",
        "13": "Kuchnia",
        "14": "Korytarz",
    }
    assert state.attributes["room_count"] == 3


async def test_room_without_name_gets_a_label(hass, cloud, loaded) -> None:
    rooms = {"rooms": [{"id": 15, "name": ""}]}
    await refresh(hass, cloud, loaded, {PropertyRef(2, 16): json.dumps(rooms)})
    assert hass.states.get(ROOMS).state == "Pokój 15"


@pytest.mark.parametrize(
    ("status", "task", "state", "location"),
    [
        (2, "", "Station", "station"),
        (7, json.dumps({"rooms": [12, 13]}), "Washing mops", "washing_mops"),
        (20, json.dumps({"rooms": [12, 13]}), "Returning to station", "returning"),
        (14, "", "Station working", "station_working"),
        (5, "", "Paused", "paused"),
        (4, json.dumps({"rooms": [12, 13]}), "Unknown", "unknown"),
        (4, json.dumps({"rooms": [13]}), "Kuchnia", "room"),
    ],
)
async def test_location(hass, cloud, loaded, status, task, state, location) -> None:
    await refresh(
        hass,
        cloud,
        loaded,
        {PropertyRef(2, 2): status, PropertyRef(2, 40): task, PropertyRef(3, 2): 0},
    )
    sensor = hass.states.get(LOCATION)
    assert sensor.state == state
    assert sensor.attributes["location"] == location
    assert sensor.attributes["miot_status"] == status


async def test_single_room_task_is_marked_as_assumed(hass, cloud, loaded) -> None:
    await refresh(
        hass,
        cloud,
        loaded,
        {PropertyRef(2, 2): 4, PropertyRef(2, 40): json.dumps({"rooms": [13]})},
    )
    attributes = hass.states.get(LOCATION).attributes
    assert attributes["confidence"] == "assumed"
    assert attributes["source"] == "single_room_cleaning_task"


async def test_position_with_room_is_exact(hass, cloud, loaded) -> None:
    await refresh(
        hass,
        cloud,
        loaded,
        {PropertyRef(2, 2): 4, PropertyRef(10, 4): json.dumps({"room_id": 14})},
    )
    sensor = hass.states.get(LOCATION)
    assert sensor.state == "Korytarz"
    assert sensor.attributes["confidence"] == "exact"


async def test_fault_code_from_2_3_is_exposed(hass, cloud, loaded) -> None:
    """Pojedynczy kod usterki (2.3) obok listy z 2.66, do porównania w testach."""
    assert hass.states.get(ALERTS).attributes["fault_code"] is None
    await refresh(
        hass,
        cloud,
        loaded,
        {PropertyRef(2, 3): 210014, PropertyRef(2, 66): '{"fault":[210014]}'},
    )
    assert hass.states.get(ALERTS).attributes["fault_code"] == 210014
    vacuum = hass.states.get("vacuum.stefan_x20_max_control")
    assert vacuum.attributes["fault_code"] == 210014
    await refresh(hass, cloud, loaded, {PropertyRef(2, 3): "x"})
    assert hass.states.get(ALERTS).attributes["fault_code"] is None


@pytest.mark.parametrize(
    ("language", "code", "expected"),
    [
        ("en", 320008, "Bumper error: check that the bumper can spring back freely; "
         "something wound into the front brush can also cause it"),
        ("pl", 320008, "Błąd zderzaka: sprawdź, czy zderzak może się prawidłowo "
         "odbić; przyczyną może być też coś wkręconego w przednią szczotkę"),
        ("pl", 210030, "Poziom wody w zbiorniku na czystą wodę jest niski"),
        ("en", 320002, "Brush error"),
        ("pl", 320004, "Zablokowane koło jezdne"),
        ("pl", 210014, "Uchwyt wkładu myjącego odpadł od odkurzacza automatycznego. "
         "Zamontuj uchwyt wkładu myjącego, aby kontynuować"),
        ("en", 100008, "100008"),  # sprzeczne źródła: tylko numer
        ("en", 0, None),
    ],
)
async def test_fault_code_description(
    hass, cloud, loaded, language, code, expected
) -> None:
    """Aktywna usterka: kod z 2.3 jest też na bieżącej liście 2.66."""
    hass.config.language = language
    await refresh(
        hass,
        cloud,
        loaded,
        {PropertyRef(2, 3): code, PropertyRef(2, 66): json.dumps({"fault": [code]})},
    )
    assert hass.states.get(ALERTS).attributes["fault_code_description"] == expected
    vacuum = hass.states.get("vacuum.stefan_x20_max_control")
    assert vacuum.attributes["fault_code_description"] == expected


async def test_past_fault_has_no_description(hass, cloud, loaded) -> None:
    """2.3 trzyma ostatni kod po ustąpieniu usterki (Franek 16.10: 320004)."""
    await refresh(
        hass,
        cloud,
        loaded,
        {PropertyRef(2, 3): 320004, PropertyRef(2, 66): '{"fault":[0]}'},
    )
    for entity_id in (ALERTS, "vacuum.stefan_x20_max_control"):
        attributes = hass.states.get(entity_id).attributes
        assert attributes["fault_code"] == 320004
        assert attributes["fault_code_description"] is None


async def test_description_follows_only_the_2_3_code(hass, cloud, loaded) -> None:
    """Inna aktywna usterka na 2.66 nie daje opisu ostatniego kodu z 2.3."""
    await refresh(
        hass,
        cloud,
        loaded,
        {PropertyRef(2, 3): 320004, PropertyRef(2, 66): '{"fault":[210030]}'},
    )
    assert hass.states.get(ALERTS).attributes["fault_code_description"] is None


async def test_fault_list_uses_the_same_texts(hass, cloud, loaded) -> None:
    await refresh(hass, cloud, loaded, {PropertyRef(2, 66): '{"fault":[320004,210017]}'})
    assert hass.states.get(FAULTS).state == "320004: Drive wheel blocked, 210017"


def test_every_known_fault_has_both_languages() -> None:
    from custom_components.xiaomi_x20_max.const import FAULT_DESCRIPTIONS

    assert set(FAULT_DESCRIPTIONS) == {
        100010, 210004, 210009, 210014, 210030, 320002, 320004, 320008, 320013
    }
    for english, polish in FAULT_DESCRIPTIONS.values():
        assert english and polish and english != polish
