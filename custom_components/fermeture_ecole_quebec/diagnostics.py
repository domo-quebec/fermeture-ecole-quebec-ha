"""Diagnostics support for the Fermeture école Québec integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import FermetureEcolesCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for one school."""
    coordinator: FermetureEcolesCoordinator = entry.runtime_data.coordinator
    schedule = coordinator.schedule
    return {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "schedule": {
            "morning_start": schedule.morning_start.isoformat(),
            "morning_end": schedule.morning_end.isoformat(),
            "interval_min_minutes": schedule.interval_min.total_seconds() / 60,
            "interval_max_minutes": schedule.interval_max.total_seconds() / 60,
            "evening_enabled": schedule.evening_enabled,
            "evening_start": schedule.evening_start.isoformat(),
            "evening_end": schedule.evening_end.isoformat(),
            "season_months": sorted(schedule.season_months),
            "workday_entity": coordinator.workday_entity or None,
        },
        "school": coordinator.async_diagnostics(),
    }
