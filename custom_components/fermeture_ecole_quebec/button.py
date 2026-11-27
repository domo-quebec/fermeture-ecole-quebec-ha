"""Button platform for the Fermeture école Québec integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import FermetureEcolesCoordinator
from .entity import FermetureEcolesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the force refresh button."""
    async_add_entities([SchoolRefreshButton(entry.runtime_data.coordinator)])


class SchoolRefreshButton(FermetureEcolesEntity, ButtonEntity):
    """Force an immediate refresh of the school closure data."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: FermetureEcolesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.school_id}_refresh"

    async def async_press(self) -> None:
        """Trigger a refresh bypassing the shared cache."""
        await self.coordinator.async_force_refresh(force=True)
        if not self.coordinator.last_update_success:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="refresh_failed"
            )
