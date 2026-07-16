"""Friendly X20 Max boolean controls."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import BOOL_PROPERTIES, DOMAIN, BoolProperty
from .controller import X20MaxController
from .entity import X20MaxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        X20MaxSwitch(controller, description)
        for description in BOOL_PROPERTIES
        if controller.property_is_exposed(description.ref)
    )


class X20MaxSwitch(X20MaxEntity, SwitchEntity):
    """Proxy a writable MIoT boolean."""

    def __init__(
        self, controller: X20MaxController, description: BoolProperty
    ) -> None:
        super().__init__(controller, f"switch_{description.key}")
        self.description = description
        self._attr_translation_key = description.key
        self._attr_icon = description.icon
        if description.advanced:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        value = self.controller.value_for_property(self.description.ref)
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("on", "true", "1", "yes")

    async def async_turn_on(self, **kwargs) -> None:
        await self.controller.async_set_property(self.description.ref, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.controller.async_set_property(self.description.ref, False)
