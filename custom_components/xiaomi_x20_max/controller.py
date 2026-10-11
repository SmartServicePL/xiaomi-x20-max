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
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .cloud import (
    X20MaxActionError,
    X20MaxAuthError,
    X20MaxCloud,
    X20MaxCloudError,
)
from .const import (
    CLEANING_MODES,
    CONF_DID,
    CONF_FIRMWARE,
    CONF_NAME,
    DOMAIN,
    MODEL,
    MODEL_ACTIONS,
    POLL_PROPERTIES,
    ROUTE_LEVELS,
    STATUSES,
    SUCTION_LEVELS,
    WATER_LEVELS,
    ActionRef,
    PropertyRef,
    fault_description,
)

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=30)
AVAILABLE_GRACE_SECONDS = 180
MAX_BACKOFF_SECONDS = 300
ONLINE_CHECK_SECONDS = 300
CLEANING_STATUSES = frozenset(
    status
    for status, meaning in STATUSES.items()
    if meaning.location == "cleaning"
)
PAUSED_STATUSES = frozenset(
    status
    for status, meaning in STATUSES.items()
    if meaning.location == "paused"
)
ERROR_STATUS = 15

STATUS_PROPERTY = PropertyRef(2, 2)
ROOMS_PROPERTY = PropertyRef(2, 16)
CURRENT_TASK_PROPERTY = PropertyRef(2, 40)
FAULTS_PROPERTY = PropertyRef(2, 66)
FAULT_CODE_PROPERTY = PropertyRef(2, 3)
ROOM_CLEAN_ACTION = ActionRef(2, 16)
# Generic MIoT "operation failed" code. Firmware 4.5.6_0406 returns it for
# accepted room cleaning too, but also for real refusals (no clean water,
# station fault, robot busy or offline), so the start is verified by reading
# the robot state instead of being trusted either way.
ROOM_CLEAN_UNCONFIRMED_CODE = -704083036
START_CONFIRM_PROPERTIES = (STATUS_PROPERTY, CURRENT_TASK_PROPERTY, FAULTS_PROPERTY)
# With mopping the robot first washes its mops in the station (status 7) and
# only then leaves (status 4), which takes about 3 minutes. The previous task
# often stays in 2.40 after it finished, so a repeated start with the same
# rooms can only be proven by the cleaning status.
START_CONFIRM_TIMEOUT = 300
START_CONFIRM_INTERVAL = 3


class X20MaxError(HomeAssistantError):
    """Base X20 Max error."""


class X20MaxNotReady(X20MaxError):
    """The standalone transport is not ready."""


class X20MaxAuthFailed(X20MaxError):
    """Xiaomi rejected the OAuth grant; the user has to re-authenticate."""


class X20MaxValidationError(X20MaxError, ServiceValidationError):
    """Invalid input supplied by the user (unknown room, empty list)."""


def _action_error_message(ref: ActionRef, err: X20MaxCloudError) -> str:
    if isinstance(err, X20MaxActionError):
        return f"Akcja MIoT {ref.siid}.{ref.aiid} nie powiodła się: kod {err.code}"
    return f"Akcja MIoT {ref.siid}.{ref.aiid} nie powiodła się: {err}"


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
        self._failures = 0
        self._retry_at = 0.0
        self._online: bool | None = None
        self._online_checked = 0.0

    async def async_initialize(self) -> None:
        """Fetch the first complete snapshot and start polling."""
        if self.entry.data.get("model", MODEL) != MODEL:
            raise X20MaxNotReady(
                f"Ta integracja obsługuje wyłącznie model {MODEL}"
            )
        try:
            await self.async_refresh()
        except X20MaxAuthFailed:
            raise
        except X20MaxError as err:
            raise X20MaxNotReady(str(err)) from err
        self._remove_interval = async_track_time_interval(
            self.hass, self._scheduled_refresh, POLL_INTERVAL
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
    def _scheduled_refresh(self, _now=None) -> None:
        """Poll on the regular interval, unless backing off after errors."""
        if time_module.monotonic() < self._retry_at:
            return
        self._start_refresh_task()

    @callback
    def _start_refresh_task(self) -> None:
        self.entry.async_create_background_task(
            self.hass, self._async_safe_refresh(), f"{self.name} X20 Max refresh"
        )

    async def _async_safe_refresh(self) -> None:
        """Background refresh; failures are logged and reflected in state."""
        try:
            await self.async_refresh()
        except X20MaxError:
            pass

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
        self._start_refresh_task()

    async def async_refresh(self) -> None:
        """Refresh every model-specific property in one cloud request."""
        if self._refresh_lock.locked():
            return
        async with self._refresh_lock:
            try:
                values = await self.cloud.async_get_properties(
                    self.did, POLL_PROPERTIES
                )
                if not values:
                    raise X20MaxCloudError(
                        "Xiaomi Cloud nie zwróciło żadnych danych"
                    )
            except X20MaxAuthError as err:
                self._record_failure(err)
                self._notify()
                self.entry.async_start_reauth(self.hass)
                raise X20MaxAuthFailed(f"{self.name}: {err}") from err
            except X20MaxCloudError as err:
                self._record_failure(err)
                self._notify()
                raise X20MaxError(f"{self.name}: {err}") from err
            self._values.update(values)
            self._last_success = time_module.monotonic()
            if self._failures:
                _LOGGER.info(
                    "%s: Xiaomi Cloud is responding again after %s failed "
                    "requests",
                    self.name,
                    self._failures,
                )
            self._failures = 0
            self._retry_at = 0.0
            await self._async_check_online()
            self._notify()

    def _record_failure(self, err: Exception) -> None:
        """Count a failed poll and back off exponentially (30 s to 5 min)."""
        self._failures += 1
        delay = min(
            POLL_INTERVAL.total_seconds() * 2 ** (self._failures - 1),
            MAX_BACKOFF_SECONDS,
        )
        # One second of slack so the interval tick at `delay` is not skipped.
        self._retry_at = time_module.monotonic() + delay - 1
        if self._failures == 1:
            _LOGGER.warning(
                "%s: Xiaomi Cloud request failed (%s); retrying with backoff",
                self.name,
                err,
            )
        else:
            _LOGGER.debug(
                "%s: Xiaomi Cloud request failed again (%s), next attempt in "
                "%.0f s",
                self.name,
                err,
                delay,
            )

    async def _async_check_online(self) -> None:
        """Read Xiaomi's online flag every 5 min, every poll while offline."""
        now = time_module.monotonic()
        if (
            self._online is not False
            and self._online_checked
            and now - self._online_checked < ONLINE_CHECK_SECONDS
        ):
            return
        self._online_checked = now
        try:
            online = await self.cloud.async_get_online(self.did)
        except X20MaxCloudError as err:
            _LOGGER.debug("%s: online check failed: %s", self.name, err)
            return
        if online is None:
            return
        if self._online is not None and online != self._online:
            _LOGGER.info(
                "%s: Xiaomi reports the robot %s",
                self.name,
                "online" if online else "offline",
            )
        self._online = online

    @property
    def available(self) -> bool:
        return self._online is not False and bool(
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
            raise X20MaxError(_action_error_message(ref, err)) from err
        self._schedule_delayed_refresh()
        return result.get("out") or []

    def fault_code(self) -> int | None:
        """Return the single fault code from 2.3 (0 means no fault).

        The model spec only gives its range (0-420000); it is exposed next to
        the fault list from 2.66 so both can be compared on real faults.
        """
        try:
            return int(self.value_for_property(FAULT_CODE_PROPERTY))
        except (TypeError, ValueError):
            return None

    def fault_code_description(self) -> str | None:
        """Return the text of the 2.3 fault code; an unknown code as a number."""
        code = self.fault_code()
        if not code:
            return None
        return fault_description(code, self.hass.config.language) or str(code)

    def active_fault_codes(self) -> list[int]:
        """Return non-zero fault codes from 2.66, ignoring malformed items."""
        raw = self.value_for_property(FAULTS_PROPERTY)
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return []
        faults = data.get("fault", []) if isinstance(data, dict) else []
        if not isinstance(faults, list):
            return []
        codes: list[int] = []
        for value in faults:
            try:
                code = int(value)
            except (TypeError, ValueError):
                continue
            if code != 0:
                codes.append(code)
        return codes

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

        location = STATUSES[status].location if status in STATUSES else "idle"
        if location == "cleaning":
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

        return {
            "location": location if status is not None else "unknown",
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

    async def async_ensure_rooms(self) -> list[dict[str, Any]]:
        """Return the room list, reading 2.16 again when it is missing.

        Room IDs are only sent to the robot when they can be checked against
        the active map; an unloaded, cleared or switched map is an error.
        """
        rooms = self.rooms()
        if rooms:
            return rooms
        try:
            values = await self.cloud.async_get_properties(
                self.did, (ROOMS_PROPERTY,)
            )
        except X20MaxCloudError as err:
            raise X20MaxError(
                translation_domain=DOMAIN,
                translation_key="room_map_unavailable",
            ) from err
        self._values.update(values)
        rooms = self.rooms()
        if not rooms:
            raise X20MaxError(
                translation_domain=DOMAIN,
                translation_key="room_map_unavailable",
            )
        return rooms

    async def async_resolve_rooms(self, values: Iterable[int | str]) -> list[int]:
        """Translate room IDs/names to IDs present on the active map."""
        values = list(values)
        if not values:
            raise X20MaxValidationError(
                translation_domain=DOMAIN,
                translation_key="no_rooms",
            )
        known = await self.async_ensure_rooms()
        by_name = {item["name"].casefold(): item["id"] for item in known}
        known_ids = {item["id"] for item in known}
        resolved: list[int] = []
        for value in values:
            if isinstance(value, int) or str(value).strip().isdigit():
                room_id = int(value)
                if room_id not in known_ids:
                    raise X20MaxValidationError(
                        translation_domain=DOMAIN,
                        translation_key="unknown_room_id",
                        translation_placeholders={"room_id": str(room_id)},
                    )
            else:
                key = str(value).strip().casefold()
                if key not in by_name:
                    raise X20MaxValidationError(
                        translation_domain=DOMAIN,
                        translation_key="unknown_room_name",
                        translation_placeholders={"room_name": str(value)},
                    )
                room_id = by_name[key]
            if room_id not in resolved:
                resolved.append(room_id)
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
        room_ids = await self.async_resolve_rooms(rooms)
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

        # Fresh baseline for the start check below; the cache may be 30 s old.
        try:
            self._values.update(
                await self.cloud.async_get_properties(
                    self.did, START_CONFIRM_PROPERTIES
                )
            )
        except X20MaxCloudError as err:
            _LOGGER.debug("%s: baseline read failed: %s", self.name, err)
        baseline_status = self._status_int()
        baseline_task = self.value_for_property(CURRENT_TASK_PROPERTY)

        try:
            await self.cloud.async_action(
                self.did,
                ROOM_CLEAN_ACTION.siid,
                ROOM_CLEAN_ACTION.aiid,
                [
                    {
                        "piid": 15,
                        "value": json.dumps(room_ids, separators=(",", ":")),
                    }
                ],
            )
        except X20MaxActionError as err:
            if err.code != ROOM_CLEAN_UNCONFIRMED_CODE:
                raise X20MaxError(
                    _action_error_message(ROOM_CLEAN_ACTION, err)
                ) from err
            await self._async_confirm_room_clean(
                room_ids, baseline_status, baseline_task
            )
        except X20MaxCloudError as err:
            raise X20MaxError(
                _action_error_message(ROOM_CLEAN_ACTION, err)
            ) from err
        self._schedule_delayed_refresh()

    def _room_clean_started(
        self,
        room_ids: list[int],
        baseline_status: int | None,
        baseline_task: Any,
    ) -> bool:
        """Return True when the cached state proves the requested task runs.

        Two independent proofs are accepted:
        * the active task (2.40) changed and now lists every requested room;
        * the robot entered a cleaning status it was not in before the call.
        An unchanged 2.40 is never trusted, because the robot keeps the
        previous task there after it finishes.
        """
        task = self.value_for_property(CURRENT_TASK_PROPERTY)
        current = self.current_cleaning() or {}
        task_rooms = set(current.get("room_ids") or [])
        if task != baseline_task and set(room_ids) <= task_rooms:
            return True
        status = self._status_int()
        return (
            status in CLEANING_STATUSES
            and baseline_status not in CLEANING_STATUSES
        )

    async def _async_confirm_room_clean(
        self,
        room_ids: list[int],
        baseline_status: int | None,
        baseline_task: Any,
    ) -> None:
        """Poll the robot until the room task is proven to run, else raise."""
        deadline = time_module.monotonic() + START_CONFIRM_TIMEOUT
        while time_module.monotonic() < deadline:
            await asyncio.sleep(START_CONFIRM_INTERVAL)
            try:
                values = await self.cloud.async_get_properties(
                    self.did, START_CONFIRM_PROPERTIES
                )
            except X20MaxCloudError as err:
                _LOGGER.debug("%s: start check failed: %s", self.name, err)
                continue
            if not values:
                continue
            self._values.update(values)
            self._notify()
            if self._room_clean_started(room_ids, baseline_status, baseline_task):
                return
            status = self._status_int()
            # A refusal (e.g. 210030, no clean water) pauses the robot with a
            # fault within seconds; there is no need to wait any longer. A
            # robot that was already paused before the call may still show
            # the old pause for a few seconds, so it gets the full window.
            if status == ERROR_STATUS or (
                status in PAUSED_STATUSES
                and baseline_status not in PAUSED_STATUSES
                and self.active_fault_codes()
            ):
                break
        status = self._status_int()
        faults = self.active_fault_codes()
        names = self.describe_room_ids(room_ids)
        raise X20MaxError(
            translation_domain=DOMAIN,
            translation_key="room_clean_not_started",
            translation_placeholders={
                "rooms": ", ".join(
                    f"{name} ({room_id})"
                    for room_id, name in zip(room_ids, names, strict=False)
                ),
                "status": "-" if status is None else str(status),
                "faults": ", ".join(str(code) for code in faults) or "-",
            },
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
