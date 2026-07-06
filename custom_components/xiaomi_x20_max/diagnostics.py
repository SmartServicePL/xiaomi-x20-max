"""Diagnostics for Xiaomi Robot Vacuum X20 Max."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_FIRMWARE, DOMAIN, MODEL, POLL_PROPERTIES, PropertyRef
from .controller import X20MaxController


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without Xiaomi credentials or tokens."""
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    rooms = controller.rooms()
    return {
        "did": "**REDACTED**",
        "model": MODEL,
        "transport": "independent_xiaomi_oauth",
        "available": controller.available,
        "firmware": entry.data.get(CONF_FIRMWARE),
        "polled_properties": len(POLL_PROPERTIES),
        "rooms": [{"id": room["id"], "name": "**REDACTED**"} for room in rooms],
        "status": controller.value_for_property(PropertyRef(2, 2)),
        "faults": controller.value_for_property(PropertyRef(2, 66)),
        "base_station": controller.value_for_property(PropertyRef(2, 18)),
    }
