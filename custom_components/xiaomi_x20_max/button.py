"""X20 Max action buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import BUTTON_ACTIONS, DOMAIN, ButtonAction
from .controller import X20MaxController
from .entity import X20MaxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        X20MaxButton(controller, description)
        for description in BUTTON_ACTIONS
        if controller.action_is_exposed(description.ref)
    )


class X20MaxButton(X20MaxEntity, ButtonEntity):
    """Execute a parameterless X20 Max MIoT action."""

    def __init__(
        self, controller: X20MaxController, description: ButtonAction
    ) -> None:
        super().__init__(controller, f"button_{description.key}")
        self.description = description
        self._attr_translation_key = description.key
        self._attr_icon = description.icon
        if description.advanced:
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.controller.async_action(self.description.ref)
