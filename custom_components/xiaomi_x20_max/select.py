"""Friendly X20 Max enumerated controls."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, ENUM_PROPERTIES, EnumProperty
from .controller import X20MaxController, X20MaxError
from .entity import X20MaxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        X20MaxSelect(controller, description)
        for description in ENUM_PROPERTIES
        if controller.property_is_exposed(description.ref)
    )


class X20MaxSelect(X20MaxEntity, SelectEntity):
    """Proxy a writable MIoT enum with stable, translated options."""

    def __init__(self, controller: X20MaxController, description: EnumProperty) -> None:
        super().__init__(controller, f"select_{description.key}")
        self.description = description
        self._attr_translation_key = description.key
        self._attr_icon = description.icon
        self._attr_options = list(description.options)

    @property
    def current_option(self) -> str | None:
        value = self.controller.value_for_property(self.description.ref)
        if value is None:
            return None
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None:
            for option, option_value in self.description.options.items():
                if numeric == option_value:
                    return option
        for option, source_state in self.description.source_states.items():
            if value == source_state:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        if option not in self.description.options:
            raise X20MaxError(f"Unknown option: {option}")
        await self.controller.async_set_property(
            self.description.ref, self.description.options[option]
        )
