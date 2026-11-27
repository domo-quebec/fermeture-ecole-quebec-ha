"""Base entity for the Fermeture école Québec integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONFIGURATION_URL, DOMAIN
from .coordinator import FermetureEcolesCoordinator


class FermetureEcolesEntity(CoordinatorEntity[FermetureEcolesCoordinator]):
    """Common entity behaviour: device and coordinator wiring."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FermetureEcolesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.school_id))},
            manufacturer="TVA Nouvelles",
            model="École",
            name=coordinator.device_name,
            configuration_url=CONFIGURATION_URL,
        )
