"""Shared data manager for the Fermeture école Québec integration.

Every school is a separate config entry but all of them consume the same
public ``schools/closed`` document. The manager makes sure a single HTTP
request is performed per refresh cycle, no matter how many schools are
monitored, and keeps the school list cached for the config flow.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import (
    ClosedSnapshot,
    School,
    async_fetch_closed,
    async_fetch_schools,
)
from .const import (
    CLOSED_MIN_INTERVAL,
    SCHOOL_LIST_TTL,
)

_LOGGER = logging.getLogger(__name__)


class FermetureEcolesManager:
    """Cache and de-duplicate calls to the TVA Nouvelles API."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._session = async_get_clientsession(hass)
        self._schools: list[School] | None = None
        self._schools_fetched_at: datetime | None = None
        self._closed: ClosedSnapshot | None = None
        self._closed_fetched_at: datetime | None = None
        self._schools_lock = asyncio.Lock()
        self._closed_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # School list
    # ------------------------------------------------------------------ #
    async def async_get_schools(self, *, force: bool = False) -> list[School]:
        """Return the school list, cached for 24 hours."""
        if not force and self._schools is not None and self._schools_cache_is_valid():
            return self._schools

        async with self._schools_lock:
            if (
                not force
                and self._schools is not None
                and self._schools_cache_is_valid()
            ):
                return self._schools
            schools = await async_fetch_schools(self._session)
            self._schools = schools
            self._schools_fetched_at = dt_util.utcnow()
            _LOGGER.debug("Fetched %s schools", len(schools))
            return schools

    def _schools_cache_is_valid(self) -> bool:
        return (
            self._schools is not None
            and self._schools_fetched_at is not None
            and dt_util.utcnow() - self._schools_fetched_at < SCHOOL_LIST_TTL
        )

    # ------------------------------------------------------------------ #
    # Closures
    # ------------------------------------------------------------------ #
    async def async_get_closed(
        self, *, force: bool = False, requested_at: datetime | None = None
    ) -> ClosedSnapshot:
        """Return the current closures.

        Normal refreshes are coalesced within :data:`CLOSED_MIN_INTERVAL`, so
        several schools refreshing at the same minute trigger a single HTTP
        request. ``force`` is used by the manual refresh service and always
        queries the API, unless another caller already fetched the document
        after ``requested_at`` (the moment the refresh was requested, shared by
        every school targeted by the same service call).
        """
        if not force and self._closed is not None and self._closed_cache_is_valid():
            return self._closed

        if requested_at is None:
            requested_at = dt_util.utcnow()
        async with self._closed_lock:
            if (
                self._closed is not None
                and self._closed_fetched_at is not None
                and (
                    (not force and self._closed_cache_is_valid())
                    or self._closed_fetched_at >= requested_at
                )
            ):
                # Another caller (for example another school forced by the same
                # service call) fetched the document while we waited.
                return self._closed
            snapshot = await async_fetch_closed(self._session)
            self._closed = snapshot
            self._closed_fetched_at = dt_util.utcnow()
            _LOGGER.debug(
                "Fetched %s closed schools (API lastUpdated=%s, forced=%s)",
                len(snapshot.schools),
                snapshot.raw_last_updated,
                force,
            )
            return snapshot

    def _closed_cache_is_valid(self) -> bool:
        return (
            self._closed is not None
            and self._closed_fetched_at is not None
            and dt_util.utcnow() - self._closed_fetched_at < CLOSED_MIN_INTERVAL
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    @property
    def closed_fetched_at(self) -> datetime | None:
        """Return when the current closures document was fetched."""
        return self._closed_fetched_at

    async def async_close(self) -> None:
        """Drop cached data (the Home Assistant shared session is not closed)."""
        self._schools = None
        self._schools_fetched_at = None
        self._closed = None
        self._closed_fetched_at = None
