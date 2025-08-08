"""Constants for the Mercury Energy NZ integration."""

DOMAIN = "mercury_co_nz"

# Configuration keys
CONF_ACCOUNT_NUMBER = "account_number"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Default values
DEFAULT_SCAN_INTERVAL = 60  # minutes
DEFAULT_NAME = "Mercury Energy"

# API endpoints
BASE_URL = "https://www.mercury.co.nz"
LOGIN_URL = f"{BASE_URL}/login"
USAGE_URL = f"{BASE_URL}/api/usage"

# Sensor types
SENSOR_TYPES = {
    "daily_usage": {
        "name": "Daily Usage",
        "unit": "kWh",
        "icon": "mdi:flash",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    "monthly_usage": {
        "name": "Monthly Usage",
        "unit": "kWh",
        "icon": "mdi:flash",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    "current_bill": {
        "name": "Current Bill",
        "unit": "$",
        "icon": "mdi:currency-usd",
        "device_class": "monetary",
        "state_class": "measurement",
    },
}
