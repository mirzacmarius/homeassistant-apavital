"""Constants for the Apavital integration."""

DOMAIN = "apavital"

CONF_CLIENT_CODE = "client_code"
CONF_JWT_TOKEN = "jwt_token"
CONF_LEAK_THRESHOLD = "leak_threshold"
CONF_SCAN_INTERVAL = "scan_interval"

API_URL = "https://my.apavital.ro/api/get_usage"
API_LOCATIONS_URL = "https://my.apavital.ro/api/locuriCons"

ATTR_INDEX = "index"
ATTR_CONSUMPTION = "consumption"
ATTR_TIME = "time"
ATTR_METER_SERIAL = "meter_serial"
ATTR_AVERAGE = "average"
ATTR_MEDIAN = "median"

# Defaults
DEFAULT_SCAN_INTERVAL = 60  # minutes
DEFAULT_LEAK_THRESHOLD = 0.1  # m³/hour - about 100L/hour indicates a leak

# Services
SERVICE_REFRESH = "refresh_data"

# Diagnostics keys
DIAG_API_CALLS = "api_calls"
DIAG_LAST_SUCCESS = "last_successful_update"
DIAG_ERRORS = "errors"
