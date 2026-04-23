from __future__ import annotations

DOMAIN = "rentlio_overview"
PLATFORMS = ["sensor", "calendar"]

CONF_API_KEY = "api_key"
CONF_PROPERTY_ID = "property_id"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LOOKBACK_DAYS = "lookback_days"
CONF_LOOKAHEAD_DAYS = "lookahead_days"

DEFAULT_SCAN_INTERVAL = 3600
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_LOOKAHEAD_DAYS = 30
API_BASE = "https://api.rentl.io/v1"
DEFAULT_TIMEZONE = "Europe/Zagreb"
