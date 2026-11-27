"""Sensor platform for the Fermeture école Québec integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTRIBUTION, STATE_CLOSED, STATE_OPEN
from .coordinator import FermetureEcolesCoordinator
from .entity import FermetureEcolesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors for one school."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            SchoolClosureSensor(coordinator),
            SchoolLastUpdateSensor(coordinator),
            SchoolNextUpdateSensor(coordinator),
        ]
    )


class SchoolClosureSensor(FermetureEcolesEntity, SensorEntity):
    """Current closure state of the school ("Fermée" / "Ouverte")."""

    _attr_translation_key = "closure"
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: FermetureEcolesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.school_id}_closure"

    @property
    def native_value(self) -> str | None:
        """Return the legacy friendly state."""
        data = self.coordinator.data
        if data is None:
            return None
        return STATE_CLOSED if data.closed else STATE_OPEN

    @property
    def icon(self) -> str:
        """Return an icon matching the state."""
        data = self.coordinator.data
        return "mdi:school-off" if data and data.closed else "mdi:school"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return information compatible with the historical YAML package."""
        data = self.coordinator.data
        if data is None:
            return {}
        closure = data.closure
        return {
            "school_id": data.school_id,
            "school_name": data.name,
            "town": data.town,
            "region": data.region,
            "school_board": data.school_board,
            # Legacy attribute names used by the Lovelace cards.
            "message": closure.message if closure else None,
            "information": list(closure.information) if closure else [],
            # Raw closure details.
            "closure_state": closure.state if closure else None,
            "closure_start": (
                closure.start.isoformat() if closure and closure.start else None
            ),
            "closure_end": (
                closure.end.isoformat() if closure and closure.end else None
            ),
            "last_updated": (
                data.api_last_updated.isoformat() if data.api_last_updated else None
            ),
            "last_updated_raw": data.api_last_updated_raw,
            "next_refresh": (
                self.coordinator.next_refresh.isoformat()
                if self.coordinator.next_refresh
                else None
            ),
        }


class SchoolLastUpdateSensor(FermetureEcolesEntity, SensorEntity):
    """Timestamp of the last successful refresh."""

    _attr_translation_key = "last_update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FermetureEcolesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.school_id}_last_update"

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last successful fetch."""
        return self.coordinator.data.fetched_at if self.coordinator.data else None


class SchoolNextUpdateSensor(FermetureEcolesEntity, SensorEntity):
    """Timestamp of the next scheduled refresh."""

    _attr_translation_key = "next_update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FermetureEcolesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.school_id}_next_update"

    @property
    def native_value(self) -> datetime | None:
        """Return the next scheduled refresh time."""
        return self.coordinator.next_refresh
