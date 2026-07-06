"""Native vacuum entity with X20 Max room support."""

from __future__ import annotations

from typing import Any

from homeassistant.components.vacuum import (
    Segment,
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CLEANING_MODES,
    DOMAIN,
    SUCTION_LEVELS,
    ActionRef,
    PropertyRef,
)
from .controller import X20MaxController, X20MaxError
from .entity import X20MaxEntity

ACTIVITY_MAP = {
    1: VacuumActivity.IDLE,
    2: VacuumActivity.DOCKED,
    3: VacuumActivity.IDLE,
    4: VacuumActivity.CLEANING,
    5: VacuumActivity.PAUSED,
    6: VacuumActivity.RETURNING,
    7: VacuumActivity.RETURNING,
    8: VacuumActivity.IDLE,
    9: VacuumActivity.DOCKED,
    10: VacuumActivity.CLEANING,
    11: VacuumActivity.IDLE,
    12: VacuumActivity.DOCKED,
    13: VacuumActivity.RETURNING,
    14: VacuumActivity.DOCKED,
    15: VacuumActivity.ERROR,
    16: VacuumActivity.CLEANING,
    17: VacuumActivity.CLEANING,
    18: VacuumActivity.PAUSED,
    19: VacuumActivity.RETURNING,
    20: VacuumActivity.PAUSED,
    21: VacuumActivity.RETURNING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([X20MaxVacuum(controller)])


class X20MaxVacuum(X20MaxEntity, StateVacuumEntity):
    """Full-featured X20 Max vacuum entity."""

    _attr_translation_key = "vacuum"
    _attr_icon = "mdi:robot-vacuum"
    _attr_supported_features = (
        VacuumEntityFeature.STATE
        | VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.CLEAN_AREA
    )
    _attr_fan_speed_list = list(SUCTION_LEVELS)

    def __init__(self, controller: X20MaxController) -> None:
        super().__init__(controller, "vacuum")

    @property
    def activity(self) -> VacuumActivity | None:
        value = self.controller.value_for_property(PropertyRef(2, 2))
        status: int | None = None
        try:
            status = int(value) if value is not None else None
            charging = int(self.controller.value_for_property(PropertyRef(3, 2)))
            if charging == 1 and status in (1, 2, 3, 9):
                return VacuumActivity.DOCKED
            return ACTIVITY_MAP.get(status) if status is not None else None
        except (TypeError, ValueError):
            return ACTIVITY_MAP.get(status) if status is not None else None

    @property
    def fan_speed(self) -> str | None:
        value = self.controller.value_for_property(PropertyRef(2, 9))
        value_map = {number: name for name, number in SUCTION_LEVELS.items()}
        try:
            return value_map.get(int(value)) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dnd = self.controller.decode_dnd() or {}
        return {
            "model": "xiaomi.vacuum.d109gl",
            "transport": "Independent Xiaomi Cloud OAuth",
            "room_ids": [room["id"] for room in self.controller.rooms()],
            "rooms": self.controller.rooms(),
            "miot_status": self.controller.value_for_property(PropertyRef(2, 2)),
            "charging_state": self.controller.value_for_property(PropertyRef(3, 2)),
            "cleaning_area_m2": self._number(PropertyRef(2, 6), 100),
            "cleaning_time_minutes": self._number(PropertyRef(2, 7), 60),
            "base_station": self.controller.value_for_property(PropertyRef(2, 18)),
            "current_cleaning": self.controller.value_for_property(PropertyRef(2, 40)),
            "faults": self.controller.value_for_property(PropertyRef(2, 66)),
            "dnd_start": dnd.get("start"),
            "dnd_end": dnd.get("end"),
        }

    def _number(self, ref: PropertyRef, divisor: int) -> float | None:
        value = self.controller.value_for_property(ref)
        try:
            return round(int(value) / divisor, 2) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_start(self) -> None:
        if self.activity == VacuumActivity.PAUSED:
            await self.controller.async_action(ActionRef(2, 8))
        else:
            await self.controller.async_action(ActionRef(2, 1))

    async def async_pause(self) -> None:
        await self.controller.async_action(ActionRef(2, 7))

    async def async_stop(self, **kwargs: Any) -> None:
        await self.controller.async_action(ActionRef(2, 2))

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self.controller.async_action(ActionRef(2, 3))

    async def async_locate(self, **kwargs: Any) -> None:
        await self.controller.async_action(ActionRef(6, 1))

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        if fan_speed not in SUCTION_LEVELS:
            raise X20MaxError(f"Unknown suction level: {fan_speed}")
        await self.controller.async_set_property(
            PropertyRef(2, 9), SUCTION_LEVELS[fan_speed]
        )

    async def async_get_segments(self) -> list[Segment]:
        return [
            Segment(id=str(room["id"]), name=room["name"])
            for room in self.controller.rooms()
        ]

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        await self.controller.async_clean_rooms(segment_ids)

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if command == "clean_rooms":
            values = params.get("rooms", []) if isinstance(params, dict) else params
            await self.controller.async_clean_rooms(values or [])
            return
        if command == "start_vacuum":
            await self.controller.async_set_property(
                PropertyRef(2, 4), CLEANING_MODES["vacuum"]
            )
            await self.controller.async_action(ActionRef(2, 4))
            return
        if command == "start_mop":
            await self.controller.async_action(ActionRef(2, 5))
            return
        if command == "start_vacuum_and_mop":
            await self.controller.async_action(ActionRef(2, 6))
            return
        if command == "start_vacuum_then_mop":
            await self.controller.async_set_property(
                PropertyRef(2, 4), CLEANING_MODES["vacuum_then_mop"]
            )
            await self.controller.async_action(ActionRef(2, 1))
            return
        raise X20MaxError(f"Unknown X20 Max command: {command}")
