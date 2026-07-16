"""Runtime controller for the standalone X20 Max integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import timedelta, time
import json
import logging
import re
import time as time_module
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .cloud import X20MaxCloud, X20MaxCloudError
from .const import (
    CLEANING_MODES,
    CONF_DID,
    CONF_FIRMWARE,
    CONF_NAME,
    MODEL,
    MODEL_ACTIONS,
    POLL_PROPERTIES,
    ROUTE_LEVELS,
    SUCTION_LEVELS,
    WATER_LEVELS,
    ActionRef,
    PropertyRef,
)

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=30)
AVAILABLE_GRACE_SECONDS = 180
STATION_STATUSES = {2, 3, 7, 9, 12, 14}
RETURNING_STATUSES = {6, 13, 19, 20, 21}
CLEANING_STATUSES = {4, 16, 17}
PAUSED_STATUSES = {5, 18}


class X20MaxError(HomeAssistantError):
    """Base X20 Max error."""


class X20MaxNotReady(X20MaxError):
    """The standalone transport is not ready."""


class X20MaxController:
    """Own the state cache and direct Xiaomi Cloud transport for one robot."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, cloud: X20MaxCloud
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.cloud = cloud
        self.did = str(entry.data[CONF_DID])
        self.name = str(entry.data.get(CONF_NAME) or "X20 Max")
        self._values: dict[PropertyRef, Any] = {}
        self._listeners: set[Callable[[], None]] = set()
        self._remove_interval: Callable[[], None] | None = None
        self._remove_delayed_refresh: Callable[[], None] | None = None
        self._refresh_lock = asyncio.Lock()
        self._last_success = 0.0

    async def async_initialize(self) -> None:
        """Fetch the first complete snapshot and start polling."""
        if self.entry.data.get("model", MODEL) != MODEL:
            raise X20MaxNotReady(
                f"Ta integracja obsługuje wyłącznie model {MODEL}"
            )
        try:
            await self.async_refresh()
        except X20MaxError as err:
            raise X20MaxNotReady(str(err)) from err
        self._remove_interval = async_track_time_interval(
            self.hass, self._schedule_refresh, POLL_INTERVAL
        )

    async def async_shutdown(self) -> None:
        """Release timers and listeners."""
        if self._remove_interval is not None:
            self._remove_interval()
            self._remove_interval = None
        if self._remove_delayed_refresh is not None:
            self._remove_delayed_refresh()
            self._remove_delayed_refresh = None
        self._listeners.clear()

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        @callback
        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    @callback
    def _schedule_refresh(self, _now=None) -> None:
        self.hass.async_create_task(
            self.async_refresh(), f"{self.name} X20 Max refresh"
        )

    @callback
    def _schedule_delayed_refresh(self) -> None:
        if self._remove_delayed_refresh is not None:
            self._remove_delayed_refresh()
        self._remove_delayed_refresh = async_call_later(
            self.hass, 2, self._delayed_refresh
        )

    @callback
    def _delayed_refresh(self, _now) -> None:
        self._remove_delayed_refresh = None
        self._schedule_refresh()

    async def async_refresh(self) -> None:
        """Refresh every model-specific property in one cloud request."""
        if self._refresh_lock.locked():
            return
        async with self._refresh_lock:
            try:
                values = await self.cloud.async_get_properties(
                    self.did, POLL_PROPERTIES
                )
            except X20MaxCloudError as err:
                _LOGGER.warning("Refresh failed for %s: %s", self.name, err)
                self._notify()
                raise X20MaxError(str(err)) from err
            if not values:
                raise X20MaxError(
                    f"{self.name}: Xiaomi Cloud nie zwróciło żadnych danych"
                )
            self._values.update(values)
            self._last_success = time_module.monotonic()
            self._notify()

    @property
    def available(self) -> bool:
        return bool(
            self._last_success
            and time_module.monotonic() - self._last_success
            < AVAILABLE_GRACE_SECONDS
        )

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {("xiaomi_x20_max", self.did)},
            "name": f"{self.name} X20 Max",
            "manufacturer": "Xiaomi",
            "model": "Robot Vacuum X20 Max",
            "model_id": MODEL,
            "sw_version": self.entry.data.get(CONF_FIRMWARE),
        }

    def value_for_property(self, ref: PropertyRef) -> Any:
        return self._values.get(ref)

    def property_is_exposed(self, ref: PropertyRef) -> bool:
        return ref in POLL_PROPERTIES

    def action_is_exposed(self, ref: ActionRef) -> bool:
        return ref in MODEL_ACTIONS

    async def async_set_property(self, ref: PropertyRef, value: Any) -> None:
        try:
            await self.cloud.async_set_property(self.did, ref, value)
        except X20MaxCloudError as err:
            raise X20MaxError(
                f"Ustawienie MIoT {ref.siid}.{ref.piid} nie powiodło się: {err}"
            ) from err
        self._values[ref] = value
        self._notify()
        self._schedule_delayed_refresh()

    async def async_action(
        self, ref: ActionRef, inputs: list[dict[str, Any]] | None = None
    ) -> list[Any]:
        try:
            result = await self.cloud.async_action(
                self.did, ref.siid, ref.aiid, inputs or []
            )
        except X20MaxCloudError as err:
            raise X20MaxError(
                f"Akcja MIoT {ref.siid}.{ref.aiid} nie powiodła się: {err}"
            ) from err
        self._schedule_delayed_refresh()
        return result.get("out") or []

    def rooms(self) -> list[dict[str, Any]]:
        """Return exact X20 Max room IDs and labels."""
        raw = self.value_for_property(PropertyRef(2, 16))
        if not raw:
            return []
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return []
        rooms = data.get("rooms", []) if isinstance(data, dict) else []
        result: list[dict[str, Any]] = []
        for room in rooms:
            if not isinstance(room, dict) or "id" not in room:
                continue
            try:
                room_id = int(room["id"])
            except (TypeError, ValueError):
                continue
            name = str(room.get("name") or f"Pokój {room_id}")
            result.append({"id": room_id, "name": name})
        return result

    def room_names(self) -> list[str]:
        """Return room names from the active Xiaomi map."""
        return [room["name"] for room in self.rooms()]

    def room_name_by_id(self) -> dict[int, str]:
        """Return a room ID to cloud room name map."""
        return {room["id"]: room["name"] for room in self.rooms()}

    def describe_room_ids(self, room_ids: Iterable[int | str]) -> list[str]:
        """Translate room IDs to cloud room names, preserving unknown IDs."""
        by_id = self.room_name_by_id()
        result: list[str] = []
        for value in room_ids:
            try:
                room_id = int(value)
            except (TypeError, ValueError):
                result.append(str(value))
                continue
            result.append(by_id.get(room_id) or f"Pokój {room_id}")
        return result

    def current_cleaning(self) -> dict[str, Any] | None:
        """Return the active cleaning task with room names decoded."""
        raw = self.value_for_property(PropertyRef(2, 40))
        if not raw:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return {"raw": raw}
        if not isinstance(data, dict):
            return {"raw": raw}
        result = dict(data)
        raw_rooms = data.get("rooms")
        if isinstance(raw_rooms, list):
            room_ids: list[int] = []
            for value in raw_rooms:
                try:
                    room_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            room_names = self.describe_room_ids(room_ids)
            result["room_ids"] = room_ids
            result["room_names"] = room_names
            result["room_labels"] = [
                f"{name} ({room_id})"
                for room_id, name in zip(room_ids, room_names, strict=False)
            ]
        return result

    def vacuum_position(self) -> dict[str, Any] | None:
        """Return the robot position payload exposed by the map service.

        The X20 Max MIoT spec exposes 10.4 as ``vacuum-position``.  Some
        firmware/cloud states return an empty string; when data is present we
        keep the raw payload and decode the most common room/coordinate shapes.
        """
        raw = self.value_for_property(PropertyRef(10, 4))
        if raw is None:
            return None
        if isinstance(raw, str) and not raw.strip():
            return None

        result: dict[str, Any] = {"raw": raw}
        data: Any = raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = raw.strip()
        result["data"] = data

        room_id = self._extract_room_id(data)
        if room_id is not None:
            result["room_id"] = room_id
            result["room_name"] = self.room_name_by_id().get(room_id) or f"Pokój {room_id}"

        room_name = self._extract_room_name(data)
        if room_name and "room_name" not in result:
            result["room_name"] = room_name

        point = self._extract_position_point(data)
        if point:
            result.update(point)
        return result

    def current_location(self) -> dict[str, Any]:
        """Return a conservative current-location summary for UI sensors."""
        status = self._status_int()
        position = self.vacuum_position()
        current_cleaning = self.current_cleaning()

        if position and (position.get("room_name") or position.get("room_id")):
            return {
                "location": "room",
                "room_id": position.get("room_id"),
                "room_name": position.get("room_name"),
                "source": "vacuum_position",
                "confidence": "exact",
                "miot_status": status,
                "vacuum_position": position,
                "current_cleaning": current_cleaning,
            }

        if status in STATION_STATUSES:
            location = "station"
            if status == 7:
                location = "washing_mops"
            elif status in (12, 14):
                location = "station_working"
            return {
                "location": location,
                "source": "miot_status",
                "confidence": "status",
                "miot_status": status,
                "vacuum_position": position,
                "current_cleaning": current_cleaning,
            }

        if status in RETURNING_STATUSES:
            return {
                "location": "returning",
                "source": "miot_status",
                "confidence": "status",
                "miot_status": status,
                "vacuum_position": position,
                "current_cleaning": current_cleaning,
            }

        if status in CLEANING_STATUSES:
            room_ids = (
                current_cleaning.get("room_ids", [])
                if isinstance(current_cleaning, dict)
                else []
            )
            room_names = (
                current_cleaning.get("room_names", [])
                if isinstance(current_cleaning, dict)
                else []
            )
            if len(room_ids) == 1 and room_names:
                return {
                    "location": "room",
                    "room_id": room_ids[0],
                    "room_name": room_names[0],
                    "source": "single_room_cleaning_task",
                    "confidence": "assumed",
                    "miot_status": status,
                    "vacuum_position": position,
                    "current_cleaning": current_cleaning,
                }
            return {
                "location": "unknown",
                "source": "no_exact_room_in_cloud",
                "confidence": "unknown",
                "miot_status": status,
                "vacuum_position": position,
                "current_cleaning": current_cleaning,
            }

        if status in PAUSED_STATUSES:
            return {
                "location": "paused",
                "source": "miot_status",
                "confidence": "status",
                "miot_status": status,
                "vacuum_position": position,
                "current_cleaning": current_cleaning,
            }

        if status == 10:
            location = "mapping"
        elif status == 15:
            location = "error"
        elif status is None:
            location = "unknown"
        else:
            location = "idle"
        return {
            "location": location,
            "source": "miot_status" if status is not None else "not_available",
            "confidence": "status" if status is not None else "unknown",
            "miot_status": status,
            "vacuum_position": position,
            "current_cleaning": current_cleaning,
        }

    def _status_int(self) -> int | None:
        value = self.value_for_property(PropertyRef(2, 2))
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _extract_room_id(self, data: Any) -> int | None:
        if isinstance(data, dict):
            for key in (
                "room_id",
                "roomId",
                "roomid",
                "room",
                "segment",
                "segment_id",
                "segmentId",
            ):
                if key not in data:
                    continue
                try:
                    return int(data[key])
                except (TypeError, ValueError):
                    room_id = self._extract_room_id(data[key])
                    if room_id is not None:
                        return room_id
            for key in ("position", "point", "pos", "data"):
                nested = data.get(key)
                room_id = self._extract_room_id(nested)
                if room_id is not None:
                    return room_id
        return None

    def _extract_room_name(self, data: Any) -> str | None:
        if isinstance(data, dict):
            for key in ("room_name", "roomName", "name", "room"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for key in ("position", "point", "pos", "data"):
                nested = data.get(key)
                room_name = self._extract_room_name(nested)
                if room_name:
                    return room_name
        return None

    def _extract_position_point(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            for x_key, y_key in (("x", "y"), ("X", "Y")):
                if x_key in data and y_key in data:
                    point = self._point_from_values(data.get(x_key), data.get(y_key), data.get("a") or data.get("angle"))
                    if point:
                        return point
            for key in ("position", "point", "pos", "coordinates", "coor", "data"):
                point = self._extract_position_point(data.get(key))
                if point:
                    return point
        if isinstance(data, (list, tuple)) and len(data) >= 2:
            angle = data[2] if len(data) >= 3 else None
            point = self._point_from_values(data[0], data[1], angle)
            if point:
                return point
        if isinstance(data, str):
            numbers = re.findall(r"-?\d+(?:\.\d+)?", data)
            if len(numbers) >= 2:
                angle = numbers[2] if len(numbers) >= 3 else None
                point = self._point_from_values(numbers[0], numbers[1], angle)
                if point:
                    return point
        return {}

    def _point_from_values(self, x_value: Any, y_value: Any, angle_value: Any = None) -> dict[str, Any]:
        try:
            x = float(x_value)
            y = float(y_value)
        except (TypeError, ValueError):
            return {}
        result: dict[str, Any] = {
            "x": int(x) if x.is_integer() else x,
            "y": int(y) if y.is_integer() else y,
        }
        try:
            angle = float(angle_value)
        except (TypeError, ValueError):
            return result
        result["angle"] = int(angle) if angle.is_integer() else angle
        return result

    def resolve_rooms(self, values: Iterable[int | str]) -> list[int]:
        known = self.rooms()
        by_name = {item["name"].casefold(): item["id"] for item in known}
        known_ids = {item["id"] for item in known}
        resolved: list[int] = []
        for value in values:
            if isinstance(value, int) or str(value).strip().isdigit():
                room_id = int(value)
                if known_ids and room_id not in known_ids:
                    raise X20MaxError(f"Nieznane ID pomieszczenia: {room_id}")
            else:
                key = str(value).strip().casefold()
                if key not in by_name:
                    raise X20MaxError(f"Nieznana nazwa pomieszczenia: {value}")
                room_id = by_name[key]
            if room_id not in resolved:
                resolved.append(room_id)
        if not resolved:
            raise X20MaxError("Trzeba podać co najmniej jedno pomieszczenie")
        return resolved

    async def async_clean_rooms(
        self,
        rooms: Iterable[int | str],
        *,
        mode: str | None = None,
        suction: str | None = None,
        water_level: str | None = None,
        passes: int | None = None,
        route: str | None = None,
    ) -> None:
        """Apply optional preferences and start one or many room IDs."""
        room_ids = self.resolve_rooms(rooms)
        settings: list[tuple[PropertyRef, Any]] = []
        if mode is not None:
            settings.append((PropertyRef(2, 4), CLEANING_MODES[mode]))
        if suction is not None:
            settings.append((PropertyRef(2, 9), SUCTION_LEVELS[suction]))
        if water_level is not None:
            settings.append((PropertyRef(2, 10), WATER_LEVELS[water_level]))
        if passes is not None:
            settings.append((PropertyRef(2, 8), passes))
        if route is not None:
            settings.append((PropertyRef(2, 74), ROUTE_LEVELS[route]))
        for ref, value in settings:
            await self.async_set_property(ref, value)
        await self.async_action(
            ActionRef(2, 16),
            [
                {
                    "piid": 15,
                    "value": json.dumps(room_ids, separators=(",", ":")),
                }
            ],
        )

    async def async_set_dnd(
        self, start: time, end: time, enabled: bool = True
    ) -> None:
        packed = (
            (start.hour << 24)
            | (start.minute << 16)
            | (end.hour << 8)
            | end.minute
        )
        await self.async_set_property(PropertyRef(11, 2), packed)
        await self.async_set_property(PropertyRef(11, 1), enabled)

    def decode_dnd(self) -> dict[str, str] | None:
        raw = self.value_for_property(PropertyRef(11, 2))
        try:
            value = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
        if value is None:
            return None
        return {
            "start": f"{(value >> 24) & 0xFF:02d}:{(value >> 16) & 0xFF:02d}",
            "end": f"{(value >> 8) & 0xFF:02d}:{value & 0xFF:02d}",
        }
