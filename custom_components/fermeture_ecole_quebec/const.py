"""Constants for the Fermeture école Québec integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "fermeture_ecole_quebec"

URL_SCHOOL_LIST: Final = "https://www.tvanouvelles.ca/api/schools/list"
URL_SCHOOL_CLOSED: Final = "https://www.tvanouvelles.ca/api/schools/closed"
ATTRIBUTION: Final = "Données fournies par TVA Nouvelles"
CONFIGURATION_URL: Final = "https://www.tvanouvelles.ca/ecoles-fermees"

PLATFORMS: Final = (
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
)

# Config entry data
CONF_SCHOOL_ID: Final = "school_id"
CONF_SCHOOL_NAME: Final = "school_name"
CONF_SCHOOL_TOWN: Final = "school_town"

# Config/options flow input keys
CONF_SEARCH: Final = "search"
CONF_SEARCH_AGAIN: Final = "search_again"
CONF_MANUAL_ID: Final = "manual_id"
CONF_SCHOOL: Final = "school"
CONF_CHANGE_SCHOOL: Final = "change_school"

# Options
CONF_SEASON: Final = "season"
CONF_SEASON_MONTHS: Final = "season_months"
CONF_MORNING_START: Final = "morning_start"
CONF_MORNING_END: Final = "morning_end"
CONF_INTERVAL_MIN: Final = "interval_min"
CONF_INTERVAL_MAX: Final = "interval_max"
CONF_EVENING_ENABLED: Final = "evening_enabled"
CONF_EVENING_START: Final = "evening_start"
CONF_EVENING_END: Final = "evening_end"
CONF_WORKDAY_ENTITY: Final = "workday_entity"

DEFAULT_SEASON: Final = True
DEFAULT_SEASON_MONTHS: Final = [10, 11, 12, 1, 2, 3, 4]
DEFAULT_MORNING_START: Final = "05:00:00"
DEFAULT_MORNING_END: Final = "08:00:00"
DEFAULT_INTERVAL_MIN: Final = 15
DEFAULT_INTERVAL_MAX: Final = 20
DEFAULT_EVENING_ENABLED: Final = True
DEFAULT_EVENING_START: Final = "17:00:00"
DEFAULT_EVENING_END: Final = "21:00:00"
DEFAULT_WORKDAY_ENTITY: Final = ""

MIN_INTERVAL_MINUTES: Final = 5
MAX_INTERVAL_MINUTES: Final = 120

# Morning slots are only set up on school days; the evening slot prepares the
# next school day (Sunday to Thursday evenings).
MORNING_WEEKDAYS: Final = frozenset({0, 1, 2, 3, 4})
EVENING_WEEKDAYS: Final = frozenset({6, 0, 1, 2, 3})

# Networking / caching
REQUEST_TIMEOUT: Final = 30
SCHOOL_LIST_TTL: Final = timedelta(hours=24)
CLOSED_MIN_INTERVAL: Final = timedelta(seconds=90)

# Coordinator behaviour
LATE_SLOT_TOLERANCE: Final = timedelta(minutes=30)
RETRY_DELAY_MIN: Final = 60
RETRY_DELAY_MAX: Final = 120
MAX_RETRIES: Final = 2

# Service
SERVICE_REFRESH: Final = "refresh"
ATTR_FORCE: Final = "force"

# Values
STATE_CLOSED: Final = "Fermée"
STATE_OPEN: Final = "Ouverte"

DATA_MANAGER: Final = "manager"
