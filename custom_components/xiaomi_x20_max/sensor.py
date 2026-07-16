"""Useful X20 Max telemetry and maintenance sensors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfArea,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, PropertyRef
from .controller import X20MaxController
from .entity import X20MaxEntity


FAULT_DESCRIPTIONS_EN: dict[int, str] = {
    210030: "Clean water tank level is low",
}

FAULT_DESCRIPTIONS_PL: dict[int, str] = {
    210030: "Poziom wody w zbiorniku na czystą wodę jest niski",
}


@dataclass(frozen=True, kw_only=True)
class X20MaxSensorDescription(SensorEntityDescription):
    """Describe an X20 Max sensor."""

    ref: PropertyRef
    value_kind: str = "int"
    json_key: str | None = None
    scale: float = 1
    remaining_ref: PropertyRef | None = None


SENSORS: tuple[X20MaxSensorDescription, ...] = (
    X20MaxSensorDescription(
        key="battery",
        translation_key="battery",
        ref=PropertyRef(3, 1),
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="cleaning_area",
        translation_key="cleaning_area",
        ref=PropertyRef(2, 6),
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        device_class=SensorDeviceClass.AREA,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.01,
    ),
    X20MaxSensorDescription(
        key="cleaning_time",
        translation_key="cleaning_time",
        ref=PropertyRef(2, 7),
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="last_clean",
        translation_key="last_clean",
        ref=PropertyRef(2, 17),
        device_class=SensorDeviceClass.TIMESTAMP,
        value_kind="timestamp",
    ),
    X20MaxSensorDescription(
        key="total_cleaning_area",
        translation_key="total_cleaning_area",
        ref=PropertyRef(10, 3),
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        device_class=SensorDeviceClass.AREA,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_kind="json",
        json_key="total_area",
        scale=0.001,
    ),
    X20MaxSensorDescription(
        key="total_cleaning_time",
        translation_key="total_cleaning_time",
        ref=PropertyRef(10, 3),
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_kind="json",
        json_key="total_time",
    ),
    X20MaxSensorDescription(
        key="total_cleaning_count",
        translation_key="total_cleaning_count",
        ref=PropertyRef(10, 3),
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_kind="json",
        json_key="total_count",
    ),
    X20MaxSensorDescription(
        key="mop_life",
        translation_key="mop_life",
        ref=PropertyRef(9, 1),
        remaining_ref=PropertyRef(9, 2),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="main_brush_life",
        translation_key="main_brush_life",
        ref=PropertyRef(12, 1),
        remaining_ref=PropertyRef(12, 2),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="side_brush_life",
        translation_key="side_brush_life",
        ref=PropertyRef(13, 1),
        remaining_ref=PropertyRef(13, 2),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="filter_life",
        translation_key="filter_life",
        ref=PropertyRef(14, 1),
        remaining_ref=PropertyRef(14, 2),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="detergent_level",
        translation_key="detergent_level",
        ref=PropertyRef(18, 1),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="dust_bag_life",
        translation_key="dust_bag_life",
        ref=PropertyRef(19, 1),
        remaining_ref=PropertyRef(19, 2),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    X20MaxSensorDescription(
        key="faults",
        translation_key="faults",
        ref=PropertyRef(2, 66),
        value_kind="faults",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    entities = [
        X20MaxSensor(controller, description)
        for description in SENSORS
        if controller.property_is_exposed(description.ref)
    ]
    entities.append(X20MaxRoomsSensor(controller))
    entities.append(X20MaxCurrentLocationSensor(controller))
    entities.append(X20MaxStationAlertsSensor(controller))
    async_add_entities(entities)


class X20MaxSensor(X20MaxEntity, SensorEntity):
    """Model-specific X20 Max sensor."""

    entity_description: X20MaxSensorDescription
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        controller: X20MaxController,
        description: X20MaxSensorDescription,
    ) -> None:
        super().__init__(controller, f"sensor_{description.key}")
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        description = self.entity_description
        raw = self.controller.value_for_property(description.ref)
        if raw is None:
            return None
        if description.value_kind == "timestamp":
            try:
                return datetime.fromtimestamp(int(raw), UTC)
            except (TypeError, ValueError, OSError):
                return None
        if description.value_kind == "json":
            try:
                data = json.loads(raw)
                value = data.get(description.json_key)
            except (TypeError, ValueError, AttributeError):
                # Xiaomi Home truncates this JSON to HA's 255-character state
                # limit, but all aggregate fields are at the beginning.
                match = re.search(
                    rf'"{re.escape(description.json_key or "")}"\s*:\s*(\d+)',
                    str(raw),
                )
                value = match.group(1) if match else None
            try:
                return round(float(value) * description.scale, 2)
            except (TypeError, ValueError):
                return None
        if description.value_kind == "faults":
            try:
                faults = json.loads(raw).get("fault", [])
            except (TypeError, ValueError, AttributeError):
                return raw
            active = [
                self._format_fault(int(value)) for value in faults if int(value) != 0
            ]
            return ", ".join(active) if active else "OK"
        try:
            value = float(raw) * description.scale
        except (TypeError, ValueError):
            return None
        return int(value) if value.is_integer() else round(value, 2)

    def _format_fault(self, code: int) -> str:
        descriptions = (
            FAULT_DESCRIPTIONS_PL
            if getattr(self.hass.config, "language", "en").startswith("pl")
            else FAULT_DESCRIPTIONS_EN
        )
        description = descriptions.get(code)
        return f"{code}: {description}" if description else str(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        ref = self.entity_description.remaining_ref
        if ref is None:
            return None
        value = self.controller.value_for_property(ref)
        try:
            return {"remaining_hours": int(value)} if value is not None else None
        except (TypeError, ValueError):
            return None


class X20MaxRoomsSensor(X20MaxEntity, SensorEntity):
    """Expose cloud room names as a first-class diagnostic entity."""

    _attr_translation_key = "rooms"
    _attr_icon = "mdi:floor-plan"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: X20MaxController) -> None:
        super().__init__(controller, "sensor_rooms")

    @property
    def native_value(self) -> str | None:
        names = self.controller.room_names()
        return ", ".join(names) if names else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rooms = self.controller.rooms()
        room_names = [item["name"] for item in rooms]
        return {
            "rooms": rooms,
            "room_names": room_names,
            "room_ids": [item["id"] for item in rooms],
            "by_id": {str(item["id"]): item["name"] for item in rooms},
            "by_name": {item["name"]: item["id"] for item in rooms},
            "room_count": len(rooms),
        }


class X20MaxCurrentLocationSensor(X20MaxEntity, SensorEntity):
    """Expose the robot's current room/location without pretending precision."""

    _attr_translation_key = "current_location"
    _attr_icon = "mdi:map-marker-radius"

    _LABELS_EN = {
        "station": "Station",
        "station_working": "Station working",
        "washing_mops": "Washing mops",
        "returning": "Returning to station",
        "paused": "Paused",
        "mapping": "Mapping",
        "error": "Error",
        "idle": "Idle",
        "unknown": "Unknown",
    }
    _LABELS_PL = {
        "station": "Stacja",
        "station_working": "Praca stacji",
        "washing_mops": "Mycie mopów",
        "returning": "Powrót do stacji",
        "paused": "Pauza",
        "mapping": "Mapowanie",
        "error": "Błąd",
        "idle": "Bezczynny",
        "unknown": "Nieznane",
    }

    def __init__(self, controller: X20MaxController) -> None:
        super().__init__(controller, "sensor_current_location")

    @property
    def native_value(self) -> str | None:
        location = self.controller.current_location()
        room_name = location.get("room_name")
        if isinstance(room_name, str) and room_name:
            return room_name
        labels = self._LABELS_PL if self._is_polish else self._LABELS_EN
        return labels.get(str(location.get("location")), labels["unknown"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        location = self.controller.current_location()
        current_cleaning = location.get("current_cleaning")
        room_ids = []
        room_names = []
        room_labels = []
        if isinstance(current_cleaning, dict):
            room_ids = current_cleaning.get("room_ids") or []
            room_names = current_cleaning.get("room_names") or []
            room_labels = current_cleaning.get("room_labels") or []

        return {
            "location": location.get("location"),
            "source": location.get("source"),
            "confidence": location.get("confidence"),
            "current_room_id": location.get("room_id"),
            "current_room_name": location.get("room_name"),
            "miot_status": location.get("miot_status"),
            "vacuum_position": location.get("vacuum_position"),
            "vacuum_position_raw": self.controller.value_for_property(
                PropertyRef(10, 4)
            ),
            "map_object": self.controller.value_for_property(PropertyRef(10, 1)),
            "trajectory_object": self.controller.value_for_property(
                PropertyRef(10, 2)
            ),
            "current_map_id": self.controller.value_for_property(PropertyRef(10, 6)),
            "current_cleaning_room_ids": room_ids,
            "current_cleaning_room_names": room_names,
            "current_cleaning_room_labels": room_labels,
            "note": self._note(location),
        }

    @property
    def _is_polish(self) -> bool:
        return getattr(self.hass.config, "language", "en").startswith("pl")

    def _note(self, location: dict[str, Any]) -> str | None:
        source = location.get("source")
        if source == "no_exact_room_in_cloud":
            if self._is_polish:
                return (
                    "Robot nie zwrócił dokładnego pokoju w danych pozycji; "
                    "kolejka sprzątania jest dostępna w atrybutach."
                )
            return (
                "The robot did not expose an exact room in its position data; "
                "the cleaning queue is available in attributes."
            )
        if source == "single_room_cleaning_task":
            if self._is_polish:
                return (
                    "Pomieszczenie wynika z jedno-pokojowego zadania, a nie "
                    "z punktu robota na mapie."
                )
            return (
                "The room is inferred from a single-room task, not from the "
                "robot point on the map."
            )
        return None


class X20MaxStationAlertsSensor(X20MaxEntity, SensorEntity):
    """Combine all station and robot diagnostic messages into one sensor."""

    _attr_translation_key = "station_alerts"
    _attr_icon = "mdi:alert-circle-check-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _TEXT_REFS = (
        ("action result", PropertyRef(2, 67)),
        ("message", PropertyRef(2, 72)),
        ("reminder", PropertyRef(2, 70)),
        ("station status", PropertyRef(20, 3)),
    )

    def __init__(self, controller: X20MaxController) -> None:
        super().__init__(controller, "sensor_station_alerts")

    def _alerts(self) -> list[str]:
        alerts: list[str] = []
        raw_faults = self.controller.value_for_property(PropertyRef(2, 66))
        try:
            fault_data = (
                json.loads(raw_faults) if isinstance(raw_faults, str) else raw_faults
            )
            faults = fault_data.get("fault", []) if isinstance(fault_data, dict) else []
            active_faults = [int(value) for value in faults if int(value) != 0]
            if active_faults:
                alerts.append(self._format_faults(active_faults))
        except (TypeError, ValueError, AttributeError):
            if raw_faults:
                alerts.append(f"Fault: {raw_faults}")

        water_check = self.controller.value_for_property(PropertyRef(2, 54))
        try:
            if int(water_check) == 3:
                alerts.append("Water system check failed")
        except (TypeError, ValueError):
            pass

        for label, ref in self._TEXT_REFS:
            raw = self.controller.value_for_property(ref)
            if raw is None:
                continue
            value = str(raw).strip()
            if value and value not in ("{}", "[]", "0"):
                alerts.append(f"{label.capitalize()}: {value}")
        return alerts

    def _format_faults(self, faults: list[int]) -> str:
        descriptions = (
            FAULT_DESCRIPTIONS_PL
            if getattr(self.hass.config, "language", "en").startswith("pl")
            else FAULT_DESCRIPTIONS_EN
        )
        prefix = (
            "Kody usterek" if descriptions is FAULT_DESCRIPTIONS_PL else "Fault codes"
        )
        values = [
            (
                f"{code}: {description}"
                if (description := descriptions.get(code))
                else str(code)
            )
            for code in faults
        ]
        return f"{prefix}: " + ", ".join(values)

    @property
    def native_value(self) -> str:
        return "Problem" if self._alerts() else "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alerts = self._alerts()
        return {
            "alerts": alerts,
            "problem": "; ".join(alerts) if alerts else None,
            "base_station": self.controller.value_for_property(PropertyRef(2, 18)),
            "fault_ids": self.controller.value_for_property(PropertyRef(2, 66)),
            "notice": self.controller.value_for_property(PropertyRef(2, 72)),
            "action_result": self.controller.value_for_property(PropertyRef(2, 67)),
            "water_check_status": self.controller.value_for_property(
                PropertyRef(2, 54)
            ),
            "custom_station_status": self.controller.value_for_property(
                PropertyRef(20, 3)
            ),
        }
