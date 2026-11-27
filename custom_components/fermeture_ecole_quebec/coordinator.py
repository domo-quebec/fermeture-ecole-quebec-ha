"""Scheduler driven coordinator for the Fermeture école Québec integration."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ClosedSchool, Closure, TvaApiError, active_closure
from .const import (
    CONF_EVENING_ENABLED,
    CONF_EVENING_END,
    CONF_EVENING_START,
    CONF_INTERVAL_MAX,
    CONF_INTERVAL_MIN,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_SCHOOL_ID,
    CONF_SCHOOL_NAME,
    CONF_SCHOOL_TOWN,
    CONF_SEASON,
    CONF_SEASON_MONTHS,
    CONF_WORKDAY_ENTITY,
    DEFAULT_EVENING_ENABLED,
    DEFAULT_EVENING_END,
    DEFAULT_EVENING_START,
    DEFAULT_INTERVAL_MAX,
    DEFAULT_INTERVAL_MIN,
    DEFAULT_MORNING_END,
    DEFAULT_MORNING_START,
    DEFAULT_SEASON_MONTHS,
    DEFAULT_WORKDAY_ENTITY,
    DOMAIN,
    EVENING_WEEKDAYS,
    LATE_SLOT_TOLERANCE,
    MAX_RETRIES,
    MORNING_WEEKDAYS,
    RETRY_DELAY_MAX,
    RETRY_DELAY_MIN,
)
from .manager import FermetureEcolesManager
from .schedule import (
    OFF_SEASON_HORIZON_DAYS,
    ScheduleConfig,
    in_morning_window,
    next_slot,
    upcoming_slots,
)
from .util import as_time

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SchoolSnapshot:
    """Everything the entities need for one school."""

    school_id: int
    name: str
    town: str
    region: str | None
    school_board: str | None
    closed: bool
    closure: Closure | None
    api_last_updated: datetime | None
    api_last_updated_raw: str | None
    fetched_at: datetime


def _as_int(value: object, fallback: int) -> int:
    """Coerce a stored option into an int."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def build_schedule_config(entry: ConfigEntry) -> ScheduleConfig:
    """Build the schedule configuration from the entry options."""
    options = entry.options
    months = options.get(CONF_SEASON_MONTHS, DEFAULT_SEASON_MONTHS)
    season = bool(options.get(CONF_SEASON, True))
    try:
        season_months = frozenset(int(month) for month in months)
    except (TypeError, ValueError):
        season_months = frozenset(DEFAULT_SEASON_MONTHS)

    interval_min = _as_int(options.get(CONF_INTERVAL_MIN), DEFAULT_INTERVAL_MIN)
    interval_max = _as_int(options.get(CONF_INTERVAL_MAX), DEFAULT_INTERVAL_MAX)

    return ScheduleConfig(
        morning_start=as_time(
            options.get(CONF_MORNING_START, DEFAULT_MORNING_START), time(5, 0)
        ),
        morning_end=as_time(
            options.get(CONF_MORNING_END, DEFAULT_MORNING_END), time(8, 0)
        ),
        interval_min=timedelta(minutes=max(interval_min, 1)),
        interval_max=timedelta(minutes=max(interval_max, interval_min, 1)),
        evening_enabled=bool(
            options.get(CONF_EVENING_ENABLED, DEFAULT_EVENING_ENABLED)
        ),
        evening_start=as_time(
            options.get(CONF_EVENING_START, DEFAULT_EVENING_START), time(17, 0)
        ),
        evening_end=as_time(
            options.get(CONF_EVENING_END, DEFAULT_EVENING_END), time(21, 0)
        ),
        season_months=season_months if season else frozenset(),
        morning_weekdays=MORNING_WEEKDAYS,
        evening_weekdays=EVENING_WEEKDAYS,
    )


class FermetureEcolesCoordinator(DataUpdateCoordinator[SchoolSnapshot]):
    """Refresh one school at randomized times.

    ``update_interval`` is left to ``None``: refreshes are armed one by one
    with :func:`homeassistant.helpers.event.async_track_point_in_utc_time`
    using a per-school randomized schedule (see :mod:`.schedule`).
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FermetureEcolesManager,
    ) -> None:
        self.school_id = int(entry.data[CONF_SCHOOL_ID])
        self.school_name: str = entry.data.get(CONF_SCHOOL_NAME, "")
        self.school_town: str = entry.data.get(CONF_SCHOOL_TOWN, "")
        self.manager = manager
        self.schedule = build_schedule_config(entry)
        self.workday_entity: str = entry.options.get(
            CONF_WORKDAY_ENTITY, DEFAULT_WORKDAY_ENTITY
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.school_id}",
            update_interval=None,
            always_update=True,
        )
        self._schedule_key = f"{entry.entry_id}:{self.school_id}"
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._force_next = False
        self._force_requested_at: datetime | None = None
        self._retries = 0
        self.next_refresh: datetime | None = None

    @property
    def device_name(self) -> str:
        """Return the device (school) display name."""
        if not self.school_name:
            return f"École {self.school_id}"
        if self.school_town:
            return f"École {self.school_name} ({self.school_town})"
        return f"École {self.school_name}"

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def async_start(self) -> None:
        """Perform one initial refresh, then arm the scheduler.

        The initial refresh happens once per Home Assistant start, whatever
        the time of day, so entities are populated immediately instead of
        waiting for the next window. Requests are coalesced by the manager,
        so several schools only cost a single HTTP call.

        A failure here makes Home Assistant retry the setup with a backoff,
        instead of leaving an idle integration behind until the next slot.
        """
        await self.async_config_entry_first_refresh()
        self._schedule_next()

    @callback
    def async_stop(self) -> None:
        """Cancel the pending timer."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
        self.next_refresh = None

    # ------------------------------------------------------------------ #
    # Scheduling
    # ------------------------------------------------------------------ #
    @callback
    def _schedule_next(self, when: datetime | None = None) -> None:
        """Arm the next refresh, either ``when`` or the next scheduled slot."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

        if when is None:
            now = dt_util.now()
            when = next_slot(self.schedule, now, self._schedule_key)
            if when is None:
                # Off-season: never leave the coordinator without a timer, or
                # it would stay idle until the next Home Assistant restart.
                when = next_slot(
                    self.schedule,
                    now,
                    self._schedule_key,
                    horizon_days=OFF_SEASON_HORIZON_DAYS,
                )
                if when is not None:
                    _LOGGER.debug(
                        "Off-season for school %s, next refresh at %s",
                        self.school_id,
                        when,
                    )

        self.next_refresh = when
        if when is None:
            _LOGGER.warning(
                "No refresh slot found for school %s, check the options",
                self.school_id,
            )
            return

        _LOGGER.debug("Next refresh for school %s at %s", self.school_id, when)
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._async_handle_slot, when
        )
        self.async_update_listeners()

    @callback
    def _async_handle_slot(self, now: datetime) -> None:
        """Run the refresh from the event loop callback."""
        self._unsub_timer = None
        self.hass.async_create_task(
            self._async_refresh_slot(now),
            f"{DOMAIN} refresh school {self.school_id}",
        )

    async def _async_refresh_slot(self, now: datetime) -> None:
        """Refresh at a scheduled slot, then arm the next one.

        ``now`` comes from :func:`async_track_point_in_utc_time`, which hands
        over UTC. Convert it before any wall clock comparison: the refresh
        windows and the workday gate are expressed in local time.
        """
        now = dt_util.as_local(now)
        slot = self.next_refresh
        if (
            slot is not None
            and self.data is not None
            and now - slot > LATE_SLOT_TOLERANCE
        ):
            _LOGGER.debug(
                "Skipping stale slot %s for school %s (%s late)",
                slot,
                self.school_id,
                now - slot,
            )
            self._schedule_next()
            return

        if not self._workday_allows(now):
            _LOGGER.debug(
                "Skipping %s refresh for school %s, not a school day",
                slot,
                self.school_id,
            )
            self._schedule_next()
            return

        try:
            await self.async_refresh()
        finally:
            # Always re-arm, even when the refresh raised unexpectedly, or the
            # integration would stop refreshing until the next restart.
            if not self.last_update_success and self._retries < MAX_RETRIES:
                self._retries += 1
                delay = random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX)
                _LOGGER.debug(
                    "Retrying school %s refresh in %.0fs (attempt %s)",
                    self.school_id,
                    delay,
                    self._retries,
                )
                self._schedule_next(now + timedelta(seconds=delay))
            else:
                self._retries = 0
                self._schedule_next()

    def _workday_allows(self, now: datetime) -> bool:
        """Return False when the optional workday entity says it is a holiday."""
        now = dt_util.as_local(now)
        if not self.workday_entity or not in_morning_window(self.schedule, now):
            return True
        state = self.hass.states.get(self.workday_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return True
        return state.state == STATE_ON

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> SchoolSnapshot:
        """Fetch the closures document and extract this school."""
        force = self._force_next
        requested_at = self._force_requested_at
        self._force_next = False
        self._force_requested_at = None
        try:
            snapshot = await self.manager.async_get_closed(
                force=force, requested_at=requested_at
            )
        except TvaApiError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.now()
        school: ClosedSchool | None = snapshot.schools.get(self.school_id)
        closure = active_closure(school.closures, now) if school else None
        # Reflect the shared document fetch time, not the moment this school
        # read it from the manager cache.
        fetched_at = self.manager.closed_fetched_at or now

        return SchoolSnapshot(
            school_id=self.school_id,
            name=(school.name if school else "") or self.school_name,
            town=(school.town if school else "") or self.school_town,
            region=school.region if school else None,
            school_board=school.school_board if school else None,
            closed=closure is not None,
            closure=closure,
            api_last_updated=snapshot.last_updated,
            api_last_updated_raw=snapshot.raw_last_updated,
            fetched_at=dt_util.as_local(fetched_at),
        )

    async def async_force_refresh(
        self, *, force: bool = True, requested_at: datetime | None = None
    ) -> None:
        """Refresh now, optionally bypassing the shared cache.

        ``requested_at`` lets every school targeted by the same service call
        share one API request instead of forcing one per school.
        """
        self._force_next = force
        self._force_requested_at = requested_at
        try:
            await self.async_refresh()
        finally:
            self._force_next = False
            self._force_requested_at = None

    # ------------------------------------------------------------------ #
    # Diagnostics
    # ------------------------------------------------------------------ #
    @callback
    def async_diagnostics(self) -> dict[str, object]:
        """Return a JSON serializable view of the current state."""
        data = self.data
        return {
            "school_id": self.school_id,
            "name": data.name if data else self.school_name,
            "town": data.town if data else self.school_town,
            "closed": data.closed if data else None,
            "message": data.closure.message if data and data.closure else None,
            "information": (
                list(data.closure.information) if data and data.closure else []
            ),
            "closure_start": (
                data.closure.start.isoformat()
                if data and data.closure and data.closure.start
                else None
            ),
            "closure_end": (
                data.closure.end.isoformat()
                if data and data.closure and data.closure.end
                else None
            ),
            "api_last_updated": (
                data.api_last_updated.isoformat()
                if data and data.api_last_updated
                else None
            ),
            "last_update_success": self.last_update_success,
            "next_refresh": (
                self.next_refresh.isoformat() if self.next_refresh else None
            ),
            "upcoming_refreshes": [
                slot.isoformat()
                for slot in upcoming_slots(
                    self.schedule, dt_util.now(), self._schedule_key, count=5
                )
            ],
        }
