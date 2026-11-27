"""Config and options flow for the Fermeture école Québec integration."""

from __future__ import annotations

import calendar
import logging
from collections.abc import Mapping
from datetime import time
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    School,
    TvaApiError,
    TvaConnectionError,
    TvaResponseError,
    async_fetch_schools,
    search_schools,
)
from .const import (
    CONF_CHANGE_SCHOOL,
    CONF_EVENING_ENABLED,
    CONF_EVENING_END,
    CONF_EVENING_START,
    CONF_INTERVAL_MAX,
    CONF_INTERVAL_MIN,
    CONF_MANUAL_ID,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_SCHOOL,
    CONF_SCHOOL_ID,
    CONF_SCHOOL_NAME,
    CONF_SCHOOL_TOWN,
    CONF_SEARCH,
    CONF_SEARCH_AGAIN,
    CONF_SEASON,
    CONF_SEASON_MONTHS,
    CONF_WORKDAY_ENTITY,
    DATA_MANAGER,
    DEFAULT_EVENING_ENABLED,
    DEFAULT_INTERVAL_MAX,
    DEFAULT_INTERVAL_MIN,
    DEFAULT_SEASON,
    DEFAULT_SEASON_MONTHS,
    DEFAULT_WORKDAY_ENTITY,
    DOMAIN,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    URL_SCHOOL_ID_LIST,
)
from .manager import FermetureEcolesManager
from .util import as_time

_LOGGER = logging.getLogger(__name__)

MAX_MATCHES = 60
WORKDAY_DOMAINS = ["binary_sensor", "input_boolean"]


def _entry_title(school: School) -> str:
    return f"{school.name} ({school.town})" if school.town else school.name


def _school_label(school: School) -> str:
    return f"{school.name} — {school.town} ({school.id})"


def _entry_data(school: School) -> dict[str, Any]:
    return {
        CONF_SCHOOL_ID: school.id,
        CONF_SCHOOL_NAME: school.name,
        CONF_SCHOOL_TOWN: school.town,
    }


def _month_options() -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(value=str(month), label=calendar.month_name[month])
        for month in range(1, 13)
    ]


def _current_time(options: Mapping[str, Any], key: str, fallback: time) -> time:
    return as_time(options.get(key), fallback)


class FermetureEcolesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick a school from the TVA Nouvelles school list."""

    VERSION = 1

    def __init__(self) -> None:
        self._schools: list[School] | None = None
        self._matches: list[School] = []
        self._total_matches = 0

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _async_get_schools(self) -> list[School]:
        """Return the school list, reusing the manager cache when available."""
        if self._schools is not None:
            return self._schools
        manager: FermetureEcolesManager | None = self.hass.data.get(DOMAIN, {}).get(
            DATA_MANAGER
        )
        if manager is not None:
            self._schools = await manager.async_get_schools()
        else:
            self._schools = await async_fetch_schools(
                async_get_clientsession(self.hass)
            )
        return self._schools

    async def _async_create_school_entry(self, school: School) -> ConfigFlowResult:
        await self.async_set_unique_id(str(school.id))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=_entry_title(school), data=_entry_data(school)
        )

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search for a school by name or town."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_MANUAL_ID):
                return await self.async_step_manual()
            query = user_input.get(CONF_SEARCH, "")
            try:
                schools = await self._async_get_schools()
            except TvaConnectionError:
                errors["base"] = "cannot_connect"
            except TvaResponseError:
                errors["base"] = "invalid_response"
            except TvaApiError:
                errors["base"] = "unknown"
            else:
                matches = search_schools(schools, query)
                if not matches:
                    errors["base"] = "no_match"
                else:
                    self._matches = matches[:MAX_MATCHES]
                    self._total_matches = len(matches)
                    return await self.async_step_school()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SEARCH, default=""): str,
                    vol.Optional(CONF_MANUAL_ID, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_school(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one of the matching schools."""
        if user_input is not None:
            if user_input.get(CONF_SEARCH_AGAIN):
                return await self.async_step_user()
            school = next(
                (
                    candidate
                    for candidate in self._matches
                    if str(candidate.id) == str(user_input.get(CONF_SCHOOL))
                ),
                None,
            )
            if school is not None:
                return await self._async_create_school_entry(school)
            return await self.async_step_user()

        return self.async_show_form(
            step_id="school",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCHOOL): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(school.id),
                                    label=_school_label(school),
                                )
                                for school in self._matches
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_SEARCH_AGAIN, default=False): bool,
                }
            ),
            description_placeholders={
                "count": str(len(self._matches)),
                "total": str(getattr(self, "_total_matches", len(self._matches))),
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fallback: enter the school id manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                school_id = int(user_input[CONF_SCHOOL_ID])
                if school_id <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_id"
            else:
                name = f"École {school_id}"
                town = ""
                try:
                    schools = await self._async_get_schools()
                except TvaApiError:
                    pass
                else:
                    match = next(
                        (item for item in schools if item.id == school_id), None
                    )
                    if match is not None:
                        name, town = match.name, match.town
                    else:
                        errors["base"] = "no_match"
                if not errors:
                    return await self._async_create_school_entry(
                        School(id=school_id, name=name, town=town)
                    )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {vol.Required(CONF_SCHOOL_ID): vol.All(int, vol.Range(min=1))}
            ),
            errors=errors,
            description_placeholders={"list_url": URL_SCHOOL_ID_LIST},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowWithReload:
        """Return the options flow."""
        return FermetureEcolesOptionsFlow()


class FermetureEcolesOptionsFlow(OptionsFlowWithReload):
    """Adjust refresh windows and, optionally, the monitored school."""

    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}
        self._matches: list[School] = []
        self._schools: list[School] | None = None

    @property
    def _entry(self) -> ConfigEntry:
        return self.config_entry

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _current(self) -> dict[str, Any]:
        return {**dict(self._entry.data), **dict(self._entry.options)}

    async def _async_get_schools(self) -> list[School]:
        if self._schools is not None:
            return self._schools
        manager: FermetureEcolesManager | None = self.hass.data.get(DOMAIN, {}).get(
            DATA_MANAGER
        )
        if manager is not None:
            self._schools = await manager.async_get_schools()
        else:
            self._schools = await async_fetch_schools(
                async_get_clientsession(self.hass)
            )
        return self._schools

    def _settings_schema(self) -> vol.Schema:
        current = self._current()
        workday = current.get(CONF_WORKDAY_ENTITY) or ""
        workday_key = (
            vol.Optional(CONF_WORKDAY_ENTITY, description={"suggested_value": workday})
            if workday
            else vol.Optional(CONF_WORKDAY_ENTITY)
        )
        return vol.Schema(
            {
                vol.Required(
                    CONF_SEASON, default=bool(current.get(CONF_SEASON, DEFAULT_SEASON))
                ): bool,
                vol.Required(
                    CONF_SEASON_MONTHS,
                    default=[
                        str(month)
                        for month in current.get(
                            CONF_SEASON_MONTHS, DEFAULT_SEASON_MONTHS
                        )
                    ],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_month_options(),
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_MORNING_START,
                    default=_current_time(current, CONF_MORNING_START, time(5, 0)),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_MORNING_END,
                    default=_current_time(current, CONF_MORNING_END, time(8, 0)),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_INTERVAL_MIN,
                    default=int(current.get(CONF_INTERVAL_MIN, DEFAULT_INTERVAL_MIN)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_INTERVAL_MINUTES,
                        max=MAX_INTERVAL_MINUTES,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_INTERVAL_MAX,
                    default=int(current.get(CONF_INTERVAL_MAX, DEFAULT_INTERVAL_MAX)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_INTERVAL_MINUTES,
                        max=MAX_INTERVAL_MINUTES,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_EVENING_ENABLED,
                    default=bool(
                        current.get(CONF_EVENING_ENABLED, DEFAULT_EVENING_ENABLED)
                    ),
                ): bool,
                vol.Required(
                    CONF_EVENING_START,
                    default=_current_time(current, CONF_EVENING_START, time(17, 0)),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_EVENING_END,
                    default=_current_time(current, CONF_EVENING_END, time(21, 0)),
                ): selector.TimeSelector(),
                workday_key: selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=WORKDAY_DOMAINS)
                ),
                vol.Optional(CONF_CHANGE_SCHOOL, default=False): bool,
            }
        )

    def _validate(self, user_input: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        if user_input[CONF_INTERVAL_MIN] > user_input[CONF_INTERVAL_MAX]:
            errors[CONF_INTERVAL_MIN] = "invalid_interval"
        if as_time(user_input[CONF_MORNING_START], time(5, 0)) >= as_time(
            user_input[CONF_MORNING_END], time(8, 0)
        ):
            errors[CONF_MORNING_START] = "invalid_morning_window"
        if user_input[CONF_EVENING_ENABLED] and as_time(
            user_input[CONF_EVENING_START], time(17, 0)
        ) >= as_time(user_input[CONF_EVENING_END], time(21, 0)):
            errors[CONF_EVENING_START] = "invalid_evening_window"
        if user_input[CONF_SEASON] and not user_input.get(CONF_SEASON_MONTHS):
            errors[CONF_SEASON_MONTHS] = "invalid_season_months"
        return errors

    def _build_options(self, user_input: dict[str, Any]) -> dict[str, Any]:
        months = sorted(
            {int(month) for month in user_input.get(CONF_SEASON_MONTHS, [])}
        )
        return {
            CONF_SEASON: bool(user_input[CONF_SEASON]),
            CONF_SEASON_MONTHS: months or list(DEFAULT_SEASON_MONTHS),
            CONF_MORNING_START: as_time(
                user_input[CONF_MORNING_START], time(5, 0)
            ).strftime("%H:%M:%S"),
            CONF_MORNING_END: as_time(
                user_input[CONF_MORNING_END], time(8, 0)
            ).strftime("%H:%M:%S"),
            CONF_INTERVAL_MIN: int(user_input[CONF_INTERVAL_MIN]),
            CONF_INTERVAL_MAX: int(user_input[CONF_INTERVAL_MAX]),
            CONF_EVENING_ENABLED: bool(user_input[CONF_EVENING_ENABLED]),
            CONF_EVENING_START: as_time(
                user_input[CONF_EVENING_START], time(17, 0)
            ).strftime("%H:%M:%S"),
            CONF_EVENING_END: as_time(
                user_input[CONF_EVENING_END], time(21, 0)
            ).strftime("%H:%M:%S"),
            CONF_WORKDAY_ENTITY: user_input.get(CONF_WORKDAY_ENTITY)
            or DEFAULT_WORKDAY_ENTITY,
        }

    async def _async_apply_school(self, school: School) -> dict[str, str]:
        """Switch the monitored school, if the target is not already used."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id != self._entry.entry_id and entry.unique_id == str(
                school.id
            ):
                return {"base": "already_configured"}
        self._async_remove_old_school()
        self.hass.config_entries.async_update_entry(
            self._entry,
            unique_id=str(school.id),
            title=_entry_title(school),
            data=_entry_data(school),
        )
        return {}

    @callback
    def _async_remove_old_school(self) -> None:
        """Drop the device and entities of the previously monitored school.

        Unique IDs and device identifiers are keyed by the school id, so the
        reload after a school change would otherwise leave the old device and
        its entities orphaned in the registries.
        """
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        prefix = f"{self._entry.data[CONF_SCHOOL_ID]}_"
        device_ids: set[str] = set()
        for entity_entry in er.async_entries_for_config_entry(
            entity_registry, self._entry.entry_id
        ):
            if not entity_entry.unique_id.startswith(prefix):
                continue
            if entity_entry.device_id is not None:
                device_ids.add(entity_entry.device_id)
            entity_registry.async_remove(entity_entry.entity_id)
        for device_id in device_ids:
            if device_registry.async_get(device_id) is not None:
                device_registry.async_remove_device(device_id)

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the refresh settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            change_school = user_input.pop(CONF_CHANGE_SCHOOL, False)
            errors = self._validate(user_input)
            if not errors:
                if change_school:
                    # Keep the validated settings until the new school is
                    # picked; they are saved together with the new entry data.
                    self._pending = user_input
                    return await self.async_step_search()
                return self.async_create_entry(
                    title="", data=self._build_options(user_input)
                )

        return self.async_show_form(
            step_id="init",
            data_schema=self._settings_schema(),
            errors=errors,
        )

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search for another school."""
        errors: dict[str, str] = {}

        if user_input is not None:
            query = user_input.get(CONF_SEARCH, "")
            try:
                schools = await self._async_get_schools()
            except TvaConnectionError:
                errors["base"] = "cannot_connect"
            except TvaResponseError:
                errors["base"] = "invalid_response"
            except TvaApiError:
                errors["base"] = "unknown"
            else:
                matches = [
                    school
                    for school in search_schools(schools, query)
                    if school.id != int(self._entry.data[CONF_SCHOOL_ID])
                ]
                if not matches:
                    errors["base"] = "no_match"
                else:
                    self._matches = matches[:MAX_MATCHES]
                    return await self.async_step_school()

        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Required(CONF_SEARCH, default=""): str}),
            errors=errors,
        )

    async def async_step_school(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the new school and save the settings."""
        if user_input is not None:
            school = next(
                (
                    candidate
                    for candidate in self._matches
                    if str(candidate.id) == str(user_input.get(CONF_SCHOOL))
                ),
                None,
            )
            if school is not None:
                errors = await self._async_apply_school(school)
                if not errors:
                    return self.async_create_entry(
                        title="", data=self._build_options(self._pending)
                    )
            else:
                errors = {"base": "unknown"}
            return self.async_show_form(
                step_id="school",
                data_schema=self._school_schema(),
                errors=errors,
            )

        return self.async_show_form(step_id="school", data_schema=self._school_schema())

    def _school_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_SCHOOL): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=str(school.id),
                                label=_school_label(school),
                            )
                            for school in self._matches
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
