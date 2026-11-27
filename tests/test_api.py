"""Tests for the TVA Nouvelles API parsing helpers."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.fermeture_ecole_quebec.api import (
    Closure,
    School,
    active_closure,
    parse_closed,
    parse_datetime,
    parse_school_list,
    search_schools,
)

from .const import CLOSED_BOUNDED_PAYLOAD, SCHOOL_LIST_PAYLOAD

TZ = ZoneInfo("America/Toronto")


@pytest.fixture(autouse=True)
def _toronto_timezone() -> Generator[None]:
    """Interpret the API timestamps as Quebec local time."""
    original = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(TZ)
    yield
    dt_util.set_default_time_zone(original)


def test_parse_school_list() -> None:
    """The school list is parsed and sorted as provided."""
    schools = parse_school_list(SCHOOL_LIST_PAYLOAD)
    assert [school.id for school in schools] == [1274, 2874, 1197]
    assert schools[0].name == "Bonnier"
    assert schools[0].town == "Mercier"


def test_parse_closed_with_history() -> None:
    """Past and active closures are both parsed."""
    snapshot = parse_closed(CLOSED_BOUNDED_PAYLOAD)
    assert snapshot.raw_last_updated == "05-12-2023 08:39:18"
    assert snapshot.last_updated == datetime(2023, 12, 5, 8, 39, 18, tzinfo=TZ)

    school = snapshot.schools[1274]
    assert school.region == "Montérégie"
    assert school.school_board == "Centre de services scolaire des Grandes-Seigneuries"
    assert len(school.closures) == 2
    assert school.closures[0].information == ("Cours suspendus",)


def test_active_closure_ignores_history() -> None:
    """Only the closure covering now is returned."""
    snapshot = parse_closed(CLOSED_BOUNDED_PAYLOAD)
    closures = snapshot.schools[1274].closures

    assert active_closure(closures, datetime(2023, 12, 5, 9, 0, tzinfo=TZ)) is not None
    assert active_closure(closures, datetime(2023, 12, 5, 23, 0, tzinfo=TZ)) is None


def test_active_closure_supports_missing_end() -> None:
    """Open ended closures (no end date) remain active."""
    closure = Closure(
        id=1,
        state="closed",
        start=datetime(2023, 12, 5, 5, 0, tzinfo=TZ),
        end=None,
        message=None,
        information=(),
    )
    assert active_closure([closure], datetime(2030, 1, 1, tzinfo=TZ)) is closure


def test_parse_nanoseconds_and_tva_format() -> None:
    """Both timestamp formats used by the API are supported."""
    assert parse_datetime("2023-12-05T08:39:19.743370813") == datetime(
        2023, 12, 5, 8, 39, 19, 743370, tzinfo=TZ
    )
    assert parse_datetime("05-12-2023 08:39:18") == datetime(
        2023, 12, 5, 8, 39, 18, tzinfo=TZ
    )
    assert parse_datetime(None) is None
    assert parse_datetime("not a date") is None


def test_parse_invalid_calendar_date() -> None:
    """Impossible dates and offsets are rejected instead of raising."""
    assert parse_datetime("2026-02-30T05:00:00") is None
    assert parse_datetime("2026-01-01T05:00:00+25:00") is None


def test_naive_timestamps_use_quebec_time() -> None:
    """Naive API values are anchored to Quebec, not to the HA timezone."""
    previous = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(ZoneInfo("Europe/Paris"))
    try:
        # 08:39 in Quebec (EST) is 13:39 UTC and 14:39 in Paris.
        parsed = parse_datetime("2023-12-05T08:39:19")
        assert parsed == datetime(2023, 12, 5, 13, 39, 19, tzinfo=UTC)
    finally:
        dt_util.set_default_time_zone(previous)


def test_search_ignores_accents_and_case() -> None:
    """Searching is accent and case insensitive, and matches the town."""
    schools = [
        School(id=1, name="à l’Orée-des-Bois", town="Drummondville"),
        School(id=2, name="Bonnier", town="Mercier"),
    ]
    assert [school.id for school in search_schools(schools, "oree des bois")] == [1]
    assert [school.id for school in search_schools(schools, "MERCIER")] == [2]
    assert [school.id for school in search_schools(schools, "2")] == [2]
    assert search_schools(schools, "inconnue") == []
    assert len(search_schools(schools, "")) == 2


def test_parse_closed_empty() -> None:
    """An empty payload is valid (no school closed)."""
    snapshot = parse_closed(
        {
            "lastUpdated": "05-12-2023 09:00:00",
            "result": {"institutions": []},
            "success": True,
        }
    )
    assert snapshot.schools == {}
    assert snapshot.last_updated is not None
    assert snapshot.last_updated - timedelta(hours=1) < snapshot.last_updated
