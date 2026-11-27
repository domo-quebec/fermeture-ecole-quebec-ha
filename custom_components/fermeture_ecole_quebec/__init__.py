"""The Fermeture école Québec integration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_extract_config_entry_ids
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import ATTR_FORCE, DATA_MANAGER, DOMAIN, PLATFORMS, SERVICE_REFRESH
from .coordinator import FermetureEcolesCoordinator
from .manager import FermetureEcolesManager

_LOGGER = logging.getLogger(__name__)

type FermetureEcolesConfigEntry = ConfigEntry[FermetureEcolesRuntimeData]


@dataclass
class FermetureEcolesRuntimeData:
    """Objects attached to a config entry at runtime."""

    coordinator: FermetureEcolesCoordinator
    manager: FermetureEcolesManager


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration wide service and the shared data manager."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if DATA_MANAGER not in domain_data:
        domain_data[DATA_MANAGER] = FermetureEcolesManager(hass)
    _async_register_services(hass)
    return True


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register ``fermeture_ecole_quebec.refresh`` once."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def _async_handle_refresh(call: ServiceCall) -> ServiceResponse:
        force = bool(call.data[ATTR_FORCE])
        extracted = async_extract_config_entry_ids(call)
        # Home Assistant made this helper async in 2025.x.
        entry_ids: set[str] = (
            await extracted if inspect.isawaitable(extracted) else extracted
        )
        coordinators: list[FermetureEcolesCoordinator] = []
        for entry_id in entry_ids:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != DOMAIN:
                continue
            runtime = getattr(entry, "runtime_data", None)
            if isinstance(runtime, FermetureEcolesRuntimeData):
                coordinators.append(runtime.coordinator)

        if not coordinators:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_target"
            )

        requested_at = dt_util.utcnow()
        await asyncio.gather(
            *(
                coordinator.async_force_refresh(force=force, requested_at=requested_at)
                for coordinator in coordinators
            )
        )
        return {
            "schools": [
                coordinator.async_diagnostics() for coordinator in coordinators
            ],
            "failed": [
                coordinator.school_id
                for coordinator in coordinators
                if not coordinator.last_update_success
            ],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        _async_handle_refresh,
        schema=cv.make_entity_service_schema(
            {vol.Optional(ATTR_FORCE, default=True): cv.boolean}
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: FermetureEcolesConfigEntry
) -> bool:
    """Set up one monitored school."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager: FermetureEcolesManager | None = domain_data.get(DATA_MANAGER)
    if manager is None:
        manager = FermetureEcolesManager(hass)
        domain_data[DATA_MANAGER] = manager

    coordinator = FermetureEcolesCoordinator(hass, entry, manager)
    entry.runtime_data = FermetureEcolesRuntimeData(
        coordinator=coordinator, manager=manager
    )
    # Covers a failure between here and the platform setup, and makes the
    # timer cleanup symmetrical with the reload path.
    entry.async_on_unload(coordinator.async_stop)

    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: FermetureEcolesConfigEntry
) -> bool:
    """Unload one monitored school."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    entry.runtime_data.coordinator.async_stop()

    remaining = [
        config_entry
        for config_entry in hass.config_entries.async_entries(DOMAIN)
        if config_entry.entry_id != entry.entry_id
    ]
    if not remaining:
        manager: FermetureEcolesManager | None = hass.data.get(DOMAIN, {}).pop(
            DATA_MANAGER, None
        )
        if manager is not None:
            await manager.async_close()

    return True
