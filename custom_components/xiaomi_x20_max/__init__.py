"""Standalone integration dedicated to Xiaomi Robot Vacuum X20 Max."""

from __future__ import annotations

from datetime import time
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)

from .cloud import X20MaxAuthError, X20MaxCloud
from .const import (
    CLEANING_MODES,
    CLOUD_DATA_KEY,
    CONF_DID,
    CONF_FIRMWARE,
    CONF_NAME,
    CONF_SOURCE_ENTITY_ID,
    DOMAIN,
    MODEL,
    PLATFORMS,
    ROUTE_LEVELS,
    STATION_ACTIONS,
    SUCTION_LEVELS,
    WATER_LEVELS,
    ActionRef,
    PropertyRef,
)
from .controller import X20MaxController, X20MaxError, X20MaxNotReady

_LOGGER = logging.getLogger(__name__)

SERVICE_CLEAN_ROOMS = "clean_rooms"
SERVICE_STATION_ACTION = "station_action"
SERVICE_SET_DND = "set_dnd"
SERVICE_SET_PROPERTY = "set_property"
SERVICE_EXECUTE_ACTION = "execute_action"

ENTITY_IDS_SCHEMA = vol.All(cv.ensure_list, [cv.entity_id])
RAW_VALUE_SCHEMA = vol.Any(bool, int, float, str, list, dict)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration-wide services."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if CLOUD_DATA_KEY not in domain_data:
        cloud = X20MaxCloud(hass)
        domain_data[CLOUD_DATA_KEY] = cloud
        try:
            await cloud.async_initialize()
        except X20MaxAuthError as err:
            _LOGGER.warning("X20 Max OAuth is not ready: %s", err)
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAN_ROOMS):
        _async_register_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate companion entries to direct cloud device IDs."""
    if entry.version >= 2 and CONF_DID in entry.data:
        return True

    cloud: X20MaxCloud = hass.data[DOMAIN][CLOUD_DATA_KEY]
    if not cloud.ready:
        await cloud.async_initialize()
    robots = await cloud.async_list_robots()
    if not robots:
        _LOGGER.error("No %s devices found while migrating %s", MODEL, entry.title)
        return False

    source_id = entry.data.get(CONF_SOURCE_ENTITY_ID)
    source_entry = er.async_get(hass).async_get(source_id) if source_id else None
    source_unique_id = source_entry.unique_id if source_entry else ""
    source_name = entry.title.removesuffix(" X20 Max")
    if source_entry and source_entry.device_id:
        device = dr.async_get(hass).async_get(source_entry.device_id)
        if device:
            source_name = device.name_by_user or device.name or source_name

    robot = next((item for item in robots if item["did"] in source_unique_id), None)
    if robot is None:
        robot = next(
            (
                item
                for item in robots
                if item["name"].casefold() == source_name.casefold()
            ),
            None,
        )
    if robot is None:
        _LOGGER.error(
            "Could not match legacy X20 Max entry %s to a cloud device",
            entry.title,
        )
        return False

    hass.config_entries.async_update_entry(
        entry,
        data={
            CONF_DID: robot["did"],
            CONF_NAME: robot["name"],
            "model": MODEL,
            CONF_FIRMWARE: robot.get("firmware"),
        },
        title=f"{robot['name']} X20 Max",
        unique_id=robot["did"],
        version=2,
    )
    _LOGGER.info("Migrated %s to standalone X20 Max transport", robot["name"])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one X20 Max."""
    cloud: X20MaxCloud = hass.data[DOMAIN][CLOUD_DATA_KEY]
    try:
        if not cloud.ready:
            await cloud.async_initialize()
        controller = X20MaxController(hass, entry, cloud)
        await controller.async_initialize()
    except (X20MaxAuthError, X20MaxNotReady) as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data[DOMAIN][entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an X20 Max."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    controller: X20MaxController | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if controller is not None:
        await controller.async_shutdown()
    return True


def _controllers_from_call(
    hass: HomeAssistant, call: ServiceCall
) -> list[X20MaxController]:
    registry = er.async_get(hass)
    controllers: list[X20MaxController] = []
    for entity_id in call.data[ATTR_ENTITY_ID]:
        item = registry.async_get(entity_id)
        if item is None or item.config_entry_id is None:
            raise ServiceValidationError(f"Unknown X20 Max entity: {entity_id}")
        controller = hass.data[DOMAIN].get(item.config_entry_id)
        if controller is None:
            raise ServiceValidationError(
                f"{entity_id} does not belong to this integration"
            )
        if controller not in controllers:
            controllers.append(controller)
    return controllers


def _service_error(err: Exception) -> ServiceValidationError:
    return ServiceValidationError(str(err))


def _async_register_services(hass: HomeAssistant) -> None:
    async def clean_rooms(call: ServiceCall) -> None:
        try:
            for controller in _controllers_from_call(hass, call):
                await controller.async_clean_rooms(
                    call.data["rooms"],
                    mode=call.data.get("mode"),
                    suction=call.data.get("suction"),
                    water_level=call.data.get("water_level"),
                    passes=call.data.get("passes"),
                    route=call.data.get("route"),
                )
        except X20MaxError as err:
            raise _service_error(err) from err

    async def station_action(call: ServiceCall) -> None:
        try:
            action = STATION_ACTIONS[call.data["action"]]
            for controller in _controllers_from_call(hass, call):
                await controller.async_action(action)
        except X20MaxError as err:
            raise _service_error(err) from err

    async def set_dnd(call: ServiceCall) -> None:
        try:
            start: time = call.data["start"]
            end: time = call.data["end"]
            for controller in _controllers_from_call(hass, call):
                await controller.async_set_dnd(
                    start, end, call.data.get("enabled", True)
                )
        except X20MaxError as err:
            raise _service_error(err) from err

    async def set_property(call: ServiceCall) -> None:
        try:
            ref = PropertyRef(call.data["siid"], call.data["piid"])
            for controller in _controllers_from_call(hass, call):
                await controller.async_set_property(ref, call.data["value"])
        except X20MaxError as err:
            raise _service_error(err) from err

    async def execute_action(call: ServiceCall) -> None:
        try:
            ref = ActionRef(call.data["siid"], call.data["aiid"])
            inputs = call.data.get("inputs", [])
            for controller in _controllers_from_call(hass, call):
                await controller.async_action(ref, inputs)
        except X20MaxError as err:
            raise _service_error(err) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAN_ROOMS,
        clean_rooms,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): ENTITY_IDS_SCHEMA,
                vol.Required("rooms"): vol.All(
                    cv.ensure_list, [vol.Any(cv.positive_int, cv.string)]
                ),
                vol.Optional("mode"): vol.In(CLEANING_MODES),
                vol.Optional("suction"): vol.In(SUCTION_LEVELS),
                vol.Optional("water_level"): vol.In(WATER_LEVELS),
                vol.Optional("passes"): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=3)
                ),
                vol.Optional("route"): vol.In(ROUTE_LEVELS),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STATION_ACTION,
        station_action,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): ENTITY_IDS_SCHEMA,
                vol.Required("action"): vol.In(STATION_ACTIONS),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DND,
        set_dnd,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): ENTITY_IDS_SCHEMA,
                vol.Required("start"): cv.time,
                vol.Required("end"): cv.time,
                vol.Optional("enabled", default=True): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PROPERTY,
        set_property,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): ENTITY_IDS_SCHEMA,
                vol.Required("siid"): cv.positive_int,
                vol.Required("piid"): cv.positive_int,
                vol.Required("value"): RAW_VALUE_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_ACTION,
        execute_action,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): ENTITY_IDS_SCHEMA,
                vol.Required("siid"): cv.positive_int,
                vol.Required("aiid"): cv.positive_int,
                vol.Optional("inputs", default=[]): [
                    {
                        vol.Required("piid"): cv.positive_int,
                        vol.Required("value"): RAW_VALUE_SCHEMA,
                    }
                ],
            }
        ),
    )
