"""Tests for the entities, the service and the shared API cache."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fermeture_ecole_quebec.const import (
    ATTRIBUTION,
    CONF_SCHOOL_ID,
    CONF_SCHOOL_NAME,
    CONF_SCHOOL_TOWN,
    DOMAIN,
    SERVICE_REFRESH,
    STATE_CLOSED,
    STATE_OPEN,
    URL_SCHOOL_CLOSED,
    URL_SCHOOL_LIST,
)
from custom_components.fermeture_ecole_quebec.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .const import CLOSED_PAYLOAD, SCHOOL_LIST_PAYLOAD

BONNIER: dict[str, Any] = {
    CONF_SCHOOL_ID: 1274,
    CONF_SCHOOL_NAME: "Bonnier",
    CONF_SCHOOL_TOWN: "Mercier",
}
OREE: dict[str, Any] = {
    CONF_SCHOOL_ID: 1197,
    CONF_SCHOOL_NAME: "à l’Orée-des-Bois",
    CONF_SCHOOL_TOWN: "Drummondville",
}


def _closed_calls(aioclient_mock: Any) -> int:
    return len(
        [call for call in aioclient_mock.mock_calls if str(call[1]).endswith("/closed")]
    )


async def _setup_entry(
    hass: HomeAssistant,
    aioclient_mock: Any,
    data: dict[str, Any],
    *,
    closed: dict[str, Any] = CLOSED_PAYLOAD,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    aioclient_mock.get(URL_SCHOOL_LIST, json=SCHOOL_LIST_PAYLOAD)
    aioclient_mock.get(URL_SCHOOL_CLOSED, json=closed)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{data[CONF_SCHOOL_NAME]} ({data[CONF_SCHOOL_TOWN]})",
        unique_id=str(data[CONF_SCHOOL_ID]),
        data=data,
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def test_closed_school_entities(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """A closed school exposes legacy compatible attributes."""
    await _setup_entry(hass, aioclient_mock, BONNIER)

    state = hass.states.get(_entity_id(hass, "sensor", "1274_closure"))
    assert state is not None
    assert state.state == STATE_CLOSED
    assert state.attributes["school_id"] == 1274
    assert state.attributes["town"] == "Mercier"
    assert state.attributes["region"] == "Montérégie"
    assert (
        state.attributes["school_board"]
        == "Centre de services scolaire des Grandes-Seigneuries"
    )
    assert state.attributes["message"] == "Le mardi 5 décembre, pour la journée"
    assert state.attributes["information"] == ["Pas de transport pour la journée"]
    assert state.attributes["closure_state"] == "closed"
    assert state.attributes["attribution"] == ATTRIBUTION
    assert state.attributes["last_updated"] is not None
    assert state.attributes["next_refresh"] is not None

    binary = hass.states.get(_entity_id(hass, "binary_sensor", "1274_closure_active"))
    assert binary is not None
    assert binary.state == "on"


async def test_open_school_entities(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """A school absent from the closures document is open."""
    await _setup_entry(hass, aioclient_mock, OREE)

    state = hass.states.get(_entity_id(hass, "sensor", "1197_closure"))
    assert state is not None
    assert state.state == STATE_OPEN
    assert state.attributes["message"] is None
    assert state.attributes["information"] == []
    assert state.attributes["region"] is None

    binary = hass.states.get(_entity_id(hass, "binary_sensor", "1197_closure_active"))
    assert binary is not None
    assert binary.state == "off"


async def test_diagnostic_timestamps(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """Last and next update sensors expose timestamps."""
    await _setup_entry(hass, aioclient_mock, BONNIER)

    last = hass.states.get(_entity_id(hass, "sensor", "1274_last_update"))
    nxt = hass.states.get(_entity_id(hass, "sensor", "1274_next_update"))
    assert last is not None and nxt is not None
    assert last.state not in ("unknown", "unavailable")
    assert nxt.state not in ("unknown", "unavailable")
    assert dt_util.parse_datetime(nxt.state) is not None


async def test_service_refresh_forces_a_call(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """The refresh service bypasses the shared cache when forced."""
    await _setup_entry(hass, aioclient_mock, BONNIER)
    entity_id = _entity_id(hass, "sensor", "1274_closure")
    assert _closed_calls(aioclient_mock) == 1

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_REFRESH,
        {"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    assert response["failed"] == []
    assert response["schools"][0]["school_id"] == 1274
    assert response["schools"][0]["closed"] is True
    assert _closed_calls(aioclient_mock) == 2

    # Without force, the shared cache is used.
    await hass.services.async_call(
        DOMAIN,
        SERVICE_REFRESH,
        {"entity_id": entity_id, "force": False},
        blocking=True,
        return_response=True,
    )
    assert _closed_calls(aioclient_mock) == 2


async def test_service_requires_a_target(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """Calling the service without a target is rejected."""
    await _setup_entry(hass, aioclient_mock, BONNIER)

    with pytest.raises(Exception) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REFRESH,
            {},
            blocking=True,
            return_response=True,
        )
    assert "entity_id" in str(err.value)


async def test_shared_cache_between_schools(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """Two schools only trigger a single closures request."""
    await _setup_entry(hass, aioclient_mock, BONNIER)
    await _setup_entry(hass, aioclient_mock, OREE)
    assert _closed_calls(aioclient_mock) == 1


async def test_unload_entry(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """Unloading stops the timer and removes the entities."""
    entry = await _setup_entry(hass, aioclient_mock, BONNIER)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """Diagnostics contain the schedule and the current state."""
    entry = await _setup_entry(hass, aioclient_mock, BONNIER)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["unique_id"] == "1274"
    assert diagnostics["schedule"]["interval_min_minutes"] == 15
    assert diagnostics["schedule"]["interval_max_minutes"] == 20
    assert sorted(diagnostics["schedule"]["season_months"]) == [1, 2, 3, 4, 10, 11, 12]
    assert diagnostics["school"]["school_id"] == 1274
    assert diagnostics["school"]["closed"] is True


async def test_workday_gate(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """The optional workday entity blocks morning refreshes on holidays."""
    entry = await _setup_entry(
        hass,
        aioclient_mock,
        BONNIER,
        options={"workday_entity": "binary_sensor.jour_ouvrable"},
    )
    coordinator = entry.runtime_data.coordinator
    monday_morning = datetime(2026, 1, 12, 6, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)

    hass.states.async_set("binary_sensor.jour_ouvrable", "off")
    # The timer callback hands over UTC; the gate must convert before comparing.
    assert coordinator._workday_allows(dt_util.as_utc(monday_morning)) is False
    assert coordinator._workday_allows(monday_morning) is False

    hass.states.async_set("binary_sensor.jour_ouvrable", "on")
    assert coordinator._workday_allows(dt_util.as_utc(monday_morning)) is True

    # The gate only applies to morning slots.
    midday = datetime(2026, 1, 12, 12, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    hass.states.async_set("binary_sensor.jour_ouvrable", "off")
    assert coordinator._workday_allows(dt_util.as_utc(midday)) is True


async def test_workday_gate_skips_scheduled_slot(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """A holiday at a morning slot skips the refresh but re-arms the schedule."""
    entry = await _setup_entry(
        hass,
        aioclient_mock,
        BONNIER,
        options={"workday_entity": "binary_sensor.jour_ouvrable"},
    )
    coordinator = entry.runtime_data.coordinator
    hass.states.async_set("binary_sensor.jour_ouvrable", "off")
    calls_before = _closed_calls(aioclient_mock)

    monday = datetime(2026, 1, 12, 6, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    coordinator.next_refresh = monday
    try:
        await coordinator._async_refresh_slot(dt_util.as_utc(monday))
        assert _closed_calls(aioclient_mock) == calls_before
        assert coordinator.next_refresh is not None
    finally:
        coordinator.async_stop()


async def test_cold_start_failure_retries_setup(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """A failing first refresh leaves the entry in SETUP_RETRY."""
    aioclient_mock.get(URL_SCHOOL_CLOSED, status=500)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bonnier (Mercier)",
        unique_id="1274",
        data=BONNIER,
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_schedule_resumes_next_season(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """Off-season, the next refresh is armed in the next season month."""
    next_month = dt_util.now().month % 12 + 1
    entry = await _setup_entry(
        hass,
        aioclient_mock,
        BONNIER,
        options={
            "season": True,
            "season_months": [next_month],
            "evening_enabled": False,
        },
    )
    coordinator = entry.runtime_data.coordinator

    assert coordinator.next_refresh is not None
    assert coordinator.next_refresh.month == next_month


async def test_failed_slot_arms_a_retry(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """A failing slot schedules a retry instead of stopping the schedule."""
    entry = await _setup_entry(hass, aioclient_mock, BONNIER)
    coordinator = entry.runtime_data.coordinator
    await entry.runtime_data.manager.async_close()

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_SCHOOL_CLOSED, status=500)
    now = dt_util.now()
    coordinator.next_refresh = now
    try:
        await coordinator._async_refresh_slot(dt_util.utcnow())
        assert coordinator._retries == 1
        assert coordinator.next_refresh is not None
        assert coordinator.next_refresh > now
    finally:
        coordinator.async_stop()


async def test_forced_refresh_coalesces_between_schools(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """Force-refreshing several schools at once still costs one request."""
    await _setup_entry(hass, aioclient_mock, BONNIER)
    await _setup_entry(hass, aioclient_mock, OREE)
    assert _closed_calls(aioclient_mock) == 1

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_REFRESH,
        {
            "entity_id": [
                _entity_id(hass, "sensor", "1274_closure"),
                _entity_id(hass, "sensor", "1197_closure"),
            ]
        },
        blocking=True,
        return_response=True,
    )

    assert response is not None
    assert response["failed"] == []
    assert len(response["schools"]) == 2
    assert _closed_calls(aioclient_mock) == 2
