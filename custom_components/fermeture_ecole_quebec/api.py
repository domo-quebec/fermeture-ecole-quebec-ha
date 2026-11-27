"""Client and parsers for the TVA Nouvelles school closure API."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unicodedata import normalize as unicode_normalize
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.util import dt as dt_util

from .const import REQUEST_TIMEOUT, URL_SCHOOL_CLOSED, URL_SCHOOL_LIST

_ISO_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T ]"
    r"(?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2}))?"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<offset>Z|[+-]\d{2}:?\d{2})?$"
)
_TVA_PATTERN = "%d-%m-%Y %H:%M:%S"
_OFFSET_PATTERN = re.compile(r"^(?P<sign>[+-])(?P<hour>\d{2}):?(?P<minute>\d{2})$")
# The TVA Nouvelles payload uses Quebec local time without an offset. Anchor
# naive values to Quebec time instead of the Home Assistant timezone.
_TVA_TIME_ZONE = ZoneInfo("America/Toronto")


class TvaApiError(Exception):
    """Base class for TVA Nouvelles API errors."""


class TvaConnectionError(TvaApiError):
    """Raised when the API cannot be reached."""


class TvaResponseError(TvaApiError):
    """Raised when the API returns an unexpected payload."""


@dataclass(frozen=True, slots=True)
class School:
    """A school from the public school list."""

    id: int
    name: str
    town: str


@dataclass(frozen=True, slots=True)
class Closure:
    """A single closure entry for a school."""

    id: int | None
    state: str | None
    start: datetime | None
    end: datetime | None
    message: str | None
    information: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClosedSchool:
    """A school as returned by the ``schools/closed`` endpoint."""

    id: int
    name: str
    town: str
    region: str | None
    school_board: str | None
    closures: tuple[Closure, ...]


@dataclass(frozen=True, slots=True)
class ClosedSnapshot:
    """Parsed payload of the ``schools/closed`` endpoint."""

    last_updated: datetime | None
    raw_last_updated: str | None
    schools: dict[int, ClosedSchool]


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _parse_offset(value: str | None) -> timezone | None:
    if not value:
        return None
    if value == "Z":
        return UTC
    match = _OFFSET_PATTERN.match(value)
    if match is None:
        raise ValueError(f"Invalid UTC offset: {value}")
    offset = timedelta(
        hours=int(match.group("hour")), minutes=int(match.group("minute"))
    )
    if match.group("sign") == "-":
        offset = -offset
    return timezone(offset, value)


def _parse_iso(value: str) -> datetime | None:
    """Parse the ISO flavour, returning None when the value is not usable."""
    match = _ISO_PATTERN.match(value)
    if match is None:
        return None
    fraction = (match.group("fraction") or "")[:6].ljust(6, "0")
    try:
        return datetime(
            year=int(match.group("date")[:4]),
            month=int(match.group("date")[5:7]),
            day=int(match.group("date")[8:10]),
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            second=int(match.group("second") or 0),
            microsecond=int(fraction),
            tzinfo=_parse_offset(match.group("offset")),
        )
    except ValueError:
        # Syntactically valid but impossible date (2026-02-30) or offset.
        return None


def parse_datetime(value: Any) -> datetime | None:
    """Parse any datetime flavour used by the two TVA Nouvelles endpoints."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()

    parsed = _parse_iso(value)
    if parsed is None:
        try:
            parsed = datetime.strptime(value, _TVA_PATTERN)
        except ValueError:
            try:
                parsed = dt_util.parse_datetime(value)
            except ValueError:
                return None
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_TVA_TIME_ZONE)
    return parsed.astimezone(dt_util.DEFAULT_TIME_ZONE)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _institutions(payload: Any) -> list[Any]:
    """Validate the envelope and return the raw institutions list."""
    if not isinstance(payload, dict):
        raise TvaResponseError("Unexpected JSON payload")
    if payload.get("success") is False:
        raise TvaResponseError("API reported an unsuccessful response")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TvaResponseError("Missing 'result' object")
    institutions = result.get("institutions")
    if not isinstance(institutions, list):
        raise TvaResponseError("Missing 'institutions' list")
    return institutions


def _parse_information(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict) and (name := _as_str(item.get("name"))):
            names.append(name)
    return tuple(names)


def _parse_closure(raw: Any) -> Closure | None:
    if not isinstance(raw, dict):
        return None
    return Closure(
        id=_as_int(raw.get("id")),
        state=_as_str(raw.get("state")),
        start=parse_datetime(raw.get("datetime_start")),
        end=parse_datetime(raw.get("datetime_end")),
        message=_as_str(raw.get("message")),
        information=_parse_information(raw.get("closure_informations")),
    )


def parse_school_list(payload: Any) -> list[School]:
    """Parse the ``schools/list`` payload."""
    schools: list[School] = []
    for raw in _institutions(payload):
        if not isinstance(raw, dict):
            continue
        school_id = _as_int(raw.get("id"))
        if school_id is None:
            continue
        schools.append(
            School(
                id=school_id,
                name=_as_str(raw.get("name")) or f"École {school_id}",
                town=_as_str(raw.get("town")) or "",
            )
        )
    return schools


def parse_closed(payload: Any) -> ClosedSnapshot:
    """Parse the ``schools/closed`` payload."""
    schools: dict[int, ClosedSchool] = {}
    for raw in _institutions(payload):
        if not isinstance(raw, dict):
            continue
        school_id = _as_int(raw.get("id"))
        if school_id is None:
            continue
        parent = raw.get("parent") if isinstance(raw.get("parent"), dict) else {}
        region = raw.get("region") or parent.get("region")
        region_name = _as_str(region.get("name")) if isinstance(region, dict) else None
        closures: list[Closure] = []
        raw_closures = raw.get("closures")
        if isinstance(raw_closures, list):
            closures = [
                closure
                for item in raw_closures
                if (closure := _parse_closure(item)) is not None
            ]
        schools[school_id] = ClosedSchool(
            id=school_id,
            name=_as_str(raw.get("name")) or f"École {school_id}",
            town=_as_str(raw.get("town")) or "",
            region=region_name,
            school_board=_as_str(parent.get("name")),
            closures=tuple(closures),
        )

    raw_last_updated = payload.get("lastUpdated") if isinstance(payload, dict) else None
    return ClosedSnapshot(
        last_updated=parse_datetime(raw_last_updated),
        raw_last_updated=_as_str(raw_last_updated),
        schools=schools,
    )


# --------------------------------------------------------------------------- #
# Selection helpers
# --------------------------------------------------------------------------- #
def active_closure(closures: Iterable[Closure], now: datetime) -> Closure | None:
    """Return the closure active at ``now``, if any.

    Missing start/end values are considered open ended so a partial payload
    still produces a useful state. When several closures overlap, the most
    recent one wins (the API keeps the full history of past closures).
    """
    active = [
        closure
        for closure in closures
        if (closure.start is None or closure.start <= now)
        and (closure.end is None or closure.end >= now)
    ]
    if not active:
        return None
    return max(active, key=lambda closure: (closure.start or now, closure.end or now))


def normalize_text(value: str) -> str:
    """Case and accent insensitive normalization used for searching."""
    return (
        unicode_normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode()
        .casefold()
        .strip()
    )


def search_schools(schools: Iterable[School], query: str) -> list[School]:
    """Return every school matching all words of ``query``."""
    normalized = normalize_text(query)
    if not normalized:
        return list(schools)
    tokens = normalized.split()
    matches: list[School] = []
    for school in schools:
        haystack = (
            f"{normalize_text(school.name)} {normalize_text(school.town)} {school.id}"
        )
        if all(token in haystack for token in tokens):
            matches.append(school)
    return matches


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
async def _async_get_json(session: aiohttp.ClientSession, url: str) -> Any:
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
    except TimeoutError as err:
        raise TvaConnectionError(f"Timeout while calling {url}") from err
    except aiohttp.ClientError as err:
        raise TvaConnectionError(f"Error while calling {url}: {err}") from err
    except ValueError as err:
        raise TvaResponseError(f"Invalid JSON from {url}: {err}") from err


async def async_fetch_schools(session: aiohttp.ClientSession) -> list[School]:
    """Fetch and parse the public school list."""
    return parse_school_list(await _async_get_json(session, URL_SCHOOL_LIST))


async def async_fetch_closed(session: aiohttp.ClientSession) -> ClosedSnapshot:
    """Fetch and parse the current closures."""
    return parse_closed(await _async_get_json(session, URL_SCHOOL_CLOSED))
