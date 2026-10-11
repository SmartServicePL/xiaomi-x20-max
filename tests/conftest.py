"""Wspólne fixture'y: integracja działa na podstawionym kliencie chmury."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xiaomi_x20_max import controller as controller_module
from custom_components.xiaomi_x20_max.cloud import X20MaxActionError
from custom_components.xiaomi_x20_max.const import (
    CLOUD_DATA_KEY,
    CONF_DID,
    CONF_FIRMWARE,
    CONF_NAME,
    DOMAIN,
    MODEL,
    PropertyRef,
)

START_CONFIRM_PROPERTIES = controller_module.START_CONFIRM_PROPERTIES
DID = "123456789"
VACUUM = "vacuum.stefan_x20_max_control"
ROOMS = [
    {"id": 12, "name": "Przedsionek"},
    {"id": 13, "name": "Kuchnia"},
    {"id": 14, "name": "Korytarz"},
]


def docked_values() -> dict[PropertyRef, Any]:
    """Robot w stacji, naładowany, bez usterek."""
    return {
        PropertyRef(2, 2): 2,
        PropertyRef(2, 16): json.dumps({"rooms": ROOMS}),
        PropertyRef(2, 40): "",
        PropertyRef(2, 66): json.dumps({"ts": 1, "fault": [0]}),
        PropertyRef(3, 1): 100,
        PropertyRef(3, 2): 1,
    }


class FakeCloud:
    """Zastępuje X20MaxCloud: trzyma właściwości i zapisuje wywołania."""

    def __init__(self) -> None:
        self.ready = True
        self.values: dict[str, dict[PropertyRef, Any]] = {DID: docked_values()}
        self.robots = [
            {
                "did": DID,
                "name": "Stefan",
                "model": MODEL,
                "firmware": "4.5.6_0406",
                "online": True,
            }
        ]
        self.actions: list[tuple[str, int, int, list[Any]]] = []
        self.writes: list[tuple[str, PropertyRef, Any]] = []
        self.action_code = 0
        self.after_action: dict[PropertyRef, Any] = {}
        self.get_error: Exception | None = None
        self.reimport_error: Exception | None = None
        self.online: bool | None = True
        # Kolejne odczyty kontrolne startu sprzątania (status, zadanie, usterki).
        self.confirm_snapshots: list[dict[PropertyRef, Any]] = []
        self.reads: list[tuple[PropertyRef, ...]] = []

    async def async_initialize(self) -> None:
        return None

    async def async_reimport(self) -> None:
        if self.reimport_error is not None:
            raise self.reimport_error

    async def async_get_properties(
        self, did: str, refs: tuple[PropertyRef, ...]
    ) -> dict[PropertyRef, Any]:
        self.reads.append(tuple(refs))
        if tuple(refs) == START_CONFIRM_PROPERTIES and self.confirm_snapshots:
            return self.confirm_snapshots.pop(0)
        if self.get_error is not None:
            raise self.get_error
        values = self.values.get(did, {})
        return {ref: values[ref] for ref in refs if ref in values}

    async def async_set_property(self, did: str, ref: PropertyRef, value: Any) -> None:
        self.writes.append((did, ref, value))
        self.values.setdefault(did, {})[ref] = value

    async def async_action(
        self, did: str, siid: int, aiid: int, inputs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.actions.append((did, siid, aiid, [item["value"] for item in inputs]))
        self.values.setdefault(did, {}).update(self.after_action)
        if self.action_code != 0:
            raise X20MaxActionError(siid, aiid, self.action_code)
        return {"code": 0, "out": []}

    async def async_get_online(self, did: str) -> bool | None:
        return self.online

    async def async_list_robots(self) -> list[dict[str, Any]]:
        return list(self.robots)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Pozwala ładować integracje z custom_components."""
    return


@pytest.fixture
def cloud(hass) -> FakeCloud:
    """Podstawiony klient chmury, zanim integracja utworzy własny."""
    fake = FakeCloud()
    hass.data.setdefault(DOMAIN, {})[CLOUD_DATA_KEY] = fake
    return fake


@pytest.fixture
def entry(hass) -> MockConfigEntry:
    """Wpis konfiguracji jednego robota."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Stefan X20 Max",
        unique_id=DID,
        version=2,
        data={
            CONF_DID: DID,
            CONF_NAME: "Stefan",
            "model": MODEL,
            CONF_FIRMWARE: "4.5.6_0406",
        },
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
async def loaded(hass, cloud, entry) -> MockConfigEntry:
    """Integracja załadowana z robotem w stacji."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def controller_of(hass, config_entry):
    """Kontroler robota z załadowanego wpisu."""
    return hass.data[DOMAIN][config_entry.entry_id]


class FakeClock:
    """Zegar sterownika: sleep przesuwa czas zamiast czekać."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def fast_clock(monkeypatch) -> FakeClock:
    """Pętla potwierdzania startu i odstępy odpytywania bez prawdziwego czekania."""
    import asyncio

    clock = FakeClock()
    real_sleep = asyncio.sleep

    async def sleep(seconds: float) -> None:
        clock.now += seconds
        await real_sleep(0)

    class FastAsyncio:
        def __getattr__(self, name: str) -> Any:
            return getattr(asyncio, name)

    fast = FastAsyncio()
    fast.sleep = sleep
    monkeypatch.setattr(controller_module, "asyncio", fast)
    monkeypatch.setattr(controller_module, "time_module", clock)
    return clock
