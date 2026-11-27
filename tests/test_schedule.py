"""Tests for the pure scheduling helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from custom_components.fermeture_ecole_quebec.schedule import (
    OFF_SEASON_HORIZON_DAYS,
    ScheduleConfig,
    build_day_slots,
    in_morning_window,
    is_school_day,
    next_slot,
    seed_for,
    upcoming_slots,
)

TZ = ZoneInfo("America/Toronto")
KEY = "entry-id:1274"


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def _evening_slots(slots: list[datetime]) -> list[datetime]:
    return [slot for slot in slots if slot.hour >= 17]


@pytest.fixture
def config() -> ScheduleConfig:
    return ScheduleConfig()


def test_seed_is_stable_and_unique(config: ScheduleConfig) -> None:
    """The same day and key always produce the same seed."""
    day = date(2026, 1, 12)
    assert seed_for(KEY, day) == seed_for(KEY, day)
    assert seed_for(KEY, day) != seed_for("other-entry:1274", day)
    assert seed_for(KEY, day) != seed_for(KEY, day + timedelta(days=1))


def test_morning_slots_are_inside_the_window(config: ScheduleConfig) -> None:
    """Morning refreshes stay between 05:00 and 08:00 with a 15-20 min gap."""
    day = date(2026, 1, 12)  # Monday
    slots = build_day_slots(config, day, KEY, TZ)

    morning = [slot for slot in slots if slot.hour < 12]
    assert 9 <= len(morning) <= 13
    assert all(_at(day, 5) <= slot <= _at(day, 8) for slot in morning)
    gaps = [b - a for a, b in pairwise(morning)]
    assert all(timedelta(minutes=15) <= gap <= timedelta(minutes=20) for gap in gaps)
    # The first refresh is jittered after 05:00 to avoid a synchronized storm.
    assert _at(day, 5) < morning[0] <= _at(day, 5, 10)


def test_no_morning_slots_on_weekend(config: ScheduleConfig) -> None:
    """Saturday and Sunday have no morning refresh."""
    saturday = date(2026, 1, 10)
    sunday = date(2026, 1, 11)
    assert not is_school_day(config, saturday)
    assert not is_school_day(config, sunday)
    assert all(slot.hour >= 17 for slot in build_day_slots(config, saturday, KEY, TZ))
    assert all(slot.hour >= 17 for slot in build_day_slots(config, sunday, KEY, TZ))


def test_no_slots_out_of_season() -> None:
    """July is outside the default October-April season."""
    assert not is_school_day(ScheduleConfig(), date(2026, 7, 6))


def test_all_year_when_season_is_empty() -> None:
    """An empty season month set means refreshes all year long."""
    config = ScheduleConfig(season_months=frozenset())
    assert is_school_day(config, date(2026, 7, 6))


def test_one_evening_slot_sunday_to_thursday(config: ScheduleConfig) -> None:
    """A single evening refresh prepares the next school day."""
    sunday_evening = build_day_slots(config, date(2026, 1, 11), KEY, TZ)
    assert _evening_slots(sunday_evening)
    evening = _evening_slots(sunday_evening)
    assert len(evening) == 1
    assert _at(date(2026, 1, 11), 17) <= evening[0] <= _at(date(2026, 1, 11), 21)

    # Friday and Saturday evenings are useless (no school the next day).
    for day in (date(2026, 1, 9), date(2026, 1, 10)):
        assert not _evening_slots(build_day_slots(config, day, KEY, TZ))


def test_evening_can_be_disabled() -> None:
    """The evening refresh is optional."""
    config = ScheduleConfig(evening_enabled=False)
    for offset in range(7):
        day = date(2026, 1, 11) + timedelta(days=offset)
        assert not _evening_slots(build_day_slots(config, day, KEY, TZ))


def test_next_slot_is_ordered_and_unique_per_key(config: ScheduleConfig) -> None:
    """Next slots increase over time and differ between schools."""
    now = _at(date(2026, 1, 12), 4, 59)
    first = next_slot(config, now, KEY)
    assert first is not None
    assert first > now

    slots = upcoming_slots(config, now, KEY, count=5)
    assert len(slots) == 5
    assert slots == sorted(slots)

    other = upcoming_slots(config, now, "other-entry:1274", count=5)
    assert slots != other


def test_next_slot_from_start_of_morning(config: ScheduleConfig) -> None:
    """Inside the morning window the next slot is soon after 05:00."""
    now = _at(date(2026, 1, 12), 5, 0)
    slot = next_slot(config, now, KEY)
    assert slot is not None
    assert slot - now <= timedelta(minutes=10)


def test_window_helpers(config: ScheduleConfig) -> None:
    """The morning window is reported consistently."""
    monday = date(2026, 1, 12)
    assert in_morning_window(config, _at(monday, 6, 0))
    assert not in_morning_window(config, _at(monday, 9, 0))

    sunday = date(2026, 1, 11)
    assert not in_morning_window(config, _at(sunday, 6, 0))


def test_next_slot_finds_next_season(config: ScheduleConfig) -> None:
    """After the last slot of the season, the next season is found."""
    may_first = _at(date(2026, 5, 1), 8, 30)
    assert next_slot(config, may_first, KEY) is None

    fallback = next_slot(config, may_first, KEY, horizon_days=OFF_SEASON_HORIZON_DAYS)
    assert fallback is not None
    # The first slot of the new season is the evening refresh that prepares
    # the first October school day.
    assert fallback.date() == date(2026, 9, 30)
    assert fallback.hour >= 17
