"""Pure scheduling helpers for the Fermeture école Québec integration.

This module deliberately has no Home Assistant imports so the schedule can be
unit tested without a Home Assistant instance.

Each school (identified by its config entry id) gets its own pseudo random
schedule that is:

* deterministic for a given ``(key, day)`` pair, so a Home Assistant restart
  does not reschedule already announced refreshes;
* unique per school, so two installations never hit the TVA Nouvelles API at
  the exact same second;
* regenerated every day, so consecutive days use different offsets.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

FIRST_SLOT_JITTER_SECONDS: int = 600
SCHEDULE_HORIZON_DAYS: int = 21
# Off-season gap (May to September with the default options): the scheduler
# must still find the first slot of the next season instead of stopping.
OFF_SEASON_HORIZON_DAYS: int = 400


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    """Refresh windows and randomized intervals."""

    morning_start: time = time(5, 0)
    morning_end: time = time(8, 0)
    interval_min: timedelta = timedelta(minutes=15)
    interval_max: timedelta = timedelta(minutes=20)
    evening_enabled: bool = True
    evening_start: time = time(17, 0)
    evening_end: time = time(21, 0)
    season_months: frozenset[int] = frozenset({10, 11, 12, 1, 2, 3, 4})
    morning_weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    evening_weekdays: frozenset[int] = frozenset({6, 0, 1, 2, 3})

    def __post_init__(self) -> None:
        """Normalize an invalid interval without raising."""
        if self.interval_max < self.interval_min:
            object.__setattr__(self, "interval_max", self.interval_min)
        if self.morning_end <= self.morning_start:
            object.__setattr__(self, "morning_end", self.morning_start)
        if self.evening_end <= self.evening_start:
            object.__setattr__(self, "evening_end", self.evening_start)


def seed_for(key: str, day: date) -> int:
    """Return a stable seed for one school and one day."""
    digest = hashlib.sha256(f"{key}:{day.isoformat()}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def in_season(config: ScheduleConfig, day: date) -> bool:
    """Return True if the day is inside the configured season."""
    return not config.season_months or day.month in config.season_months


def is_school_day(config: ScheduleConfig, day: date) -> bool:
    """Return True if morning refreshes are expected that day."""
    return day.weekday() in config.morning_weekdays and in_season(config, day)


def _combine(day: date, at: time, tz: tzinfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz)


def build_day_slots(
    config: ScheduleConfig, day: date, key: str, tz: tzinfo
) -> list[datetime]:
    """Return the refresh slots for a single day, sorted."""
    rng = random.Random(seed_for(key, day))
    slots: list[datetime] = []

    if is_school_day(config, day):
        start = _combine(day, config.morning_start, tz)
        end = _combine(day, config.morning_end, tz)
        moment = start + timedelta(seconds=rng.uniform(0, FIRST_SLOT_JITTER_SECONDS))
        while moment <= end:
            slots.append(moment)
            moment += timedelta(
                seconds=rng.uniform(
                    config.interval_min.total_seconds(),
                    config.interval_max.total_seconds(),
                )
            )

    if (
        config.evening_enabled
        and day.weekday() in config.evening_weekdays
        and is_school_day(config, day + timedelta(days=1))
    ):
        evening_start = _combine(day, config.evening_start, tz)
        evening_end = _combine(day, config.evening_end, tz)
        span = (evening_end - evening_start).total_seconds()
        slots.append(evening_start + timedelta(seconds=rng.uniform(0, span)))

    return sorted(slots)


def _iter_slots(
    config: ScheduleConfig,
    now: datetime,
    key: str,
    horizon_days: int = SCHEDULE_HORIZON_DAYS,
) -> Iterable[datetime]:
    """Yield upcoming slots, day by day, over the scheduling horizon."""
    tz = now.tzinfo
    assert tz is not None
    today = now.date()
    for offset in range(horizon_days):
        yield from build_day_slots(config, today + timedelta(days=offset), key, tz)


def next_slot(
    config: ScheduleConfig,
    now: datetime,
    key: str,
    horizon_days: int = SCHEDULE_HORIZON_DAYS,
) -> datetime | None:
    """Return the next refresh slot strictly after ``now``."""
    for slot in _iter_slots(config, now, key, horizon_days):
        if slot > now:
            return slot
    return None


def upcoming_slots(
    config: ScheduleConfig,
    now: datetime,
    key: str,
    count: int = 10,
    horizon_days: int = SCHEDULE_HORIZON_DAYS,
) -> list[datetime]:
    """Return the next ``count`` refresh slots."""
    slots: list[datetime] = []
    for slot in _iter_slots(config, now, key, horizon_days):
        if slot > now:
            slots.append(slot)
            if len(slots) >= count:
                break
    return slots


def _time_of_day(moment: datetime) -> time:
    return moment.timetz().replace(tzinfo=None)


def in_morning_window(config: ScheduleConfig, now: datetime) -> bool:
    """Return True when ``now`` is inside a morning refresh window."""
    return is_school_day(config, now.date()) and (
        config.morning_start <= _time_of_day(now) <= config.morning_end
    )
