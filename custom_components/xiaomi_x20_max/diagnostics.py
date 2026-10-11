"""Diagnostics for Xiaomi Robot Vacuum X20 Max."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_FIRMWARE, DOMAIN, MODEL, POLL_PROPERTIES, PropertyRef
from .controller import X20MaxController

REDACTED = "**REDACTED**"
TO_REDACT = {"did"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without credentials, the cloud ID or room names."""
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    data = {
        "did": controller.did,
        "model": MODEL,
        "transport": "independent_xiaomi_oauth",
        "available": controller.available,
        "firmware": entry.data.get(CONF_FIRMWARE),
        "polled_properties": len(POLL_PROPERTIES),
        # Room IDs are kept: they are needed to debug clean_rooms and are not
        # personal. Room names are chosen by the user and are redacted.
        "rooms": [
            {"id": room["id"], "name": REDACTED} for room in controller.rooms()
        ],
        "status": controller.value_for_property(PropertyRef(2, 2)),
        "faults": controller.value_for_property(PropertyRef(2, 66)),
        "base_station": controller.value_for_property(PropertyRef(2, 18)),
    }
    return async_redact_data(data, TO_REDACT)
