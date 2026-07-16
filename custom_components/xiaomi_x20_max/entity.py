"""Shared X20 Max entity base."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .controller import X20MaxController


class X20MaxEntity(Entity):
    """Entity backed by an X20 Max controller."""

    _attr_has_entity_name = True

    def __init__(self, controller: X20MaxController, key: str) -> None:
        self.controller = controller
        self._attr_unique_id = f"{controller.did}_{key}"

    @property
    def device_info(self):
        return self.controller.device_info

    @property
    def available(self) -> bool:
        return self.controller.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.controller.subscribe(self.async_write_ha_state)
        )
