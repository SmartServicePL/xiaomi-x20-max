"""Numeric X20 Max settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, PropertyRef
from .controller import X20MaxController
from .entity import X20MaxEntity


@dataclass(frozen=True, slots=True)
class NumberSetting:
    key: str
    ref: PropertyRef
    minimum: float
    maximum: float
    step: float
    unit: str
    icon: str


NUMBER_SETTINGS = (
    NumberSetting(
        "volume", PropertyRef(4, 2), 0, 100, 1, "%", "mdi:volume-high"
    ),
    NumberSetting(
        "mop_wash_interval",
        PropertyRef(2, 81),
        1,
        255,
        1,
        "min",
        "mdi:timer-sync",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: X20MaxController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        X20MaxNumber(controller, description)
        for description in NUMBER_SETTINGS
        if controller.property_is_exposed(description.ref)
    )


class X20MaxNumber(X20MaxEntity, NumberEntity):
    """Writable numeric X20 Max property."""

    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, controller: X20MaxController, description: NumberSetting
    ) -> None:
        super().__init__(controller, f"number_{description.key}")
        self.description = description
        self._attr_translation_key = description.key
        self._attr_icon = description.icon
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum
        self._attr_native_step = description.step
        self._attr_native_unit_of_measurement = description.unit

    @property
    def native_value(self) -> float | None:
        value = self.controller.value_for_property(self.description.ref)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.controller.async_set_property(
            self.description.ref, int(value)
        )
