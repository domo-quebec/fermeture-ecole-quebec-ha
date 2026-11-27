"""Tests for the config and options flows."""

from __future__ import annotations

from datetime import time
from typing import Any

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fermeture_ecole_quebec.const import (
    CONF_EVENING_ENABLED,
    CONF_INTERVAL_MAX,
    CONF_INTERVAL_MIN,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_SCHOOL_ID,
    CONF_SCHOOL_NAME,
    CONF_SCHOOL_TOWN,
    CONF_SEASON_MONTHS,
    DOMAIN,
    URL_SCHOOL_CLOSED,
    URL_SCHOOL_LIST,
)

from .const import CLOSED_PAYLOAD, SCHOOL_LIST_PAYLOAD

ENTRY_DATA: dict[str, Any] = {
    CONF_SCHOOL_ID: 1274,
    CONF_SCHOOL_NAME: "Bonnier",
    CONF_SCHOOL_TOWN: "Mercier",
}
OREE_DATA: dict[str, Any] = {
    CONF_SCHOOL_ID: 1197,
    CONF_SCHOOL_NAME: "à l’Orée-des-Bois",
    CONF_SCHOOL_TOWN: "Drummondville",
}
BASE_OPTIONS: dict[str, Any] = {
    "season": True,
    "season_months": ["10", "11", "12", "1", "2", "3", "4"],
    "morning_start": time(5, 0),
    "morning_end": time(8, 0),
    "interval_min": 15,
    "interval_max": 20,
    "evening_enabled": True,
    "evening_start": time(17, 0),
    "evening_end": time(21, 0),
    "change_school": False,
}


@pytest.fixture(autouse=True)
def mock_api(aioclient_mock: Any) -> None:
    """Mock both API endpoints."""
    aioclient_mock.get(URL_SCHOOL_LIST, json=SCHOOL_LIST_PAYLOAD)
    aioclient_mock.get(URL_SCHOOL_CLOSED, json=CLOSED_PAYLOAD)


async def _start_flow(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_full_config_flow(hass: HomeAssistant) -> None:
    """Search a school then select it."""
    result = await _start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "bonnier"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "school"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school": "1274", "search_again": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bonnier (Mercier)"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == "1274"


async def test_search_again_returns_to_search(hass: HomeAssistant) -> None:
    """The 'search again' checkbox goes back to the search step."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "bonnier"}
    )
    assert result["step_id"] == "school"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school": "1274", "search_again": True}
    )
    assert result["step_id"] == "user"


async def test_no_match(hass: HomeAssistant) -> None:
    """An unknown search keeps the user on the search step."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "aucune ecole ici"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_match"}


async def test_already_configured(hass: HomeAssistant) -> None:
    """The same school cannot be added twice."""
    MockConfigEntry(
        domain=DOMAIN, title="Bonnier (Mercier)", unique_id="1274", data=ENTRY_DATA
    ).add_to_hass(hass)

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "bonnier"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school": "1274", "search_again": False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """API errors are surfaced as a form error."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_SCHOOL_LIST, status=500)

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "bonnier"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_invalid_response(hass: HomeAssistant, aioclient_mock: Any) -> None:
    """A malformed payload is reported as an invalid response."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_SCHOOL_LIST, json={"success": True, "result": {}})

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "bonnier"}
    )
    assert result["errors"] == {"base": "invalid_response"}


async def test_manual_id(hass: HomeAssistant) -> None:
    """The manual id fallback resolves the school name."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "", "manual_id": True}
    )
    assert result["step_id"] == "manual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school_id": 1197}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "à l’Orée-des-Bois (Drummondville)"
    assert result["data"][CONF_SCHOOL_ID] == 1197


async def test_manual_unknown_id(hass: HomeAssistant) -> None:
    """An unknown id is rejected, an API failure is tolerated."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "", "manual_id": True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school_id": 999999}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_match"}


async def test_manual_id_with_api_down(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """The manual id still works when the list endpoint is unavailable."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_SCHOOL_LIST, exc=aiohttp.ClientError)
    aioclient_mock.get(URL_SCHOOL_CLOSED, json=CLOSED_PAYLOAD)

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "", "manual_id": True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school_id": 1274}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "École 1274"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Options are stored and the entry is reloaded."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Bonnier (Mercier)", unique_id="1274", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "season": True,
            "season_months": ["10", "11", "12", "1", "2", "3", "4"],
            "morning_start": time(5, 0),
            "morning_end": time(8, 0),
            "interval_min": 10,
            "interval_max": 18,
            "evening_enabled": True,
            "evening_start": time(17, 0),
            "evening_end": time(21, 0),
            "change_school": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_INTERVAL_MIN] == 10
    assert entry.options[CONF_INTERVAL_MAX] == 18
    assert entry.options[CONF_EVENING_ENABLED] is True
    assert entry.options[CONF_MORNING_START] == "05:00:00"
    assert entry.options[CONF_MORNING_END] == "08:00:00"
    assert entry.options[CONF_SEASON_MONTHS] == [1, 2, 3, 4, 10, 11, 12]


async def test_options_invalid_interval(hass: HomeAssistant) -> None:
    """A minimum interval greater than the maximum is rejected."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Bonnier (Mercier)", unique_id="1274", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "season": True,
            "season_months": ["1"],
            "morning_start": time(5, 0),
            "morning_end": time(8, 0),
            "interval_min": 30,
            "interval_max": 10,
            "evening_enabled": True,
            "evening_start": time(17, 0),
            "evening_end": time(21, 0),
            "change_school": False,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_INTERVAL_MIN: "invalid_interval"}


async def test_options_empty_season_months(hass: HomeAssistant) -> None:
    """An enabled season needs at least one month."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Bonnier (Mercier)", unique_id="1274", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "season": True,
            "season_months": [],
            "morning_start": time(5, 0),
            "morning_end": time(8, 0),
            "interval_min": 15,
            "interval_max": 20,
            "evening_enabled": True,
            "evening_start": time(17, 0),
            "evening_end": time(21, 0),
            "change_school": False,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SEASON_MONTHS: "invalid_season_months"}


async def test_options_change_school(hass: HomeAssistant) -> None:
    """Another school can be selected from the options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Bonnier (Mercier)", unique_id="1274", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "season": True,
            "season_months": ["10"],
            "morning_start": time(5, 0),
            "morning_end": time(8, 0),
            "interval_min": 15,
            "interval_max": 20,
            "evening_enabled": True,
            "evening_start": time(17, 0),
            "evening_end": time(21, 0),
            "change_school": True,
        },
    )
    assert result["step_id"] == "search"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"search": "oree"}
    )
    assert result["step_id"] == "school"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"school": "1197"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.unique_id == "1197"
    assert entry.title == "à l’Orée-des-Bois (Drummondville)"
    assert entry.data[CONF_SCHOOL_ID] == 1197

    entity_registry = er.async_get(hass)
    assert entity_registry.async_get_entity_id("sensor", DOMAIN, "1274_closure") is None
    assert (
        entity_registry.async_get_entity_id("sensor", DOMAIN, "1197_closure")
        is not None
    )
    device_registry = dr.async_get(hass)
    assert device_registry.async_get_device(identifiers={(DOMAIN, "1274")}) is None
    assert device_registry.async_get_device(identifiers={(DOMAIN, "1197")}) is not None


async def test_options_change_school_already_configured(
    hass: HomeAssistant,
) -> None:
    """Switching to a school monitored by another entry is refused."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Bonnier (Mercier)", unique_id="1274", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    MockConfigEntry(
        domain=DOMAIN,
        title="à l’Orée-des-Bois (Drummondville)",
        unique_id="1197",
        data=OREE_DATA,
    ).add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_OPTIONS, "change_school": True}
    )
    assert result["step_id"] == "search"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"search": "oree"}
    )
    assert result["step_id"] == "school"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"school": "1197"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}
    assert entry.unique_id == "1274"


async def test_options_search_invalid_response(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """A malformed school list is reported as an invalid response."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Bonnier (Mercier)", unique_id="1274", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_SCHOOL_LIST, json={"success": True, "result": {}})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_OPTIONS, "change_school": True}
    )
    assert result["step_id"] == "search"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"search": "bonnier"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_response"}
