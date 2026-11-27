"""Binary sensor platform for the Fermeture école Québec integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTRIBUTION
from .coordinator import FermetureEcolesCoordinator
from .entity import FermetureEcolesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the closure binary sensor."""
    async_add_entities([SchoolClosureBinarySensor(entry.runtime_data.coordinator)])


class SchoolClosureBinarySensor(FermetureEcolesEntity, BinarySensorEntity):
    """On when the school is currently closed."""

    _attr_translation_key = "closure_active"
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: FermetureEcolesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.school_id}_closure_active"

    @property
    def is_on(self) -> bool:
        """Return True while a closure is in progress."""
        data = self.coordinator.data
        return bool(data and data.closed)

    @property
    def icon(self) -> str:
        """Return an icon matching the state."""
        data = self.coordinator.data
        return "mdi:school-off" if data and data.closed else "mdi:school"
