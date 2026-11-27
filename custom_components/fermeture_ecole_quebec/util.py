"""Small helpers shared by the Fermeture école Québec integration."""

from __future__ import annotations

from datetime import time

from homeassistant.util import dt as dt_util


def as_time(value: object, fallback: time) -> time:
    """Coerce a stored option (``time`` or ``"HH:MM:SS"``) into a ``time``."""
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        parsed = dt_util.parse_time(value)
        if parsed is not None:
            return parsed
    return fallback
