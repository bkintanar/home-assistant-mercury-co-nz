"""Constants for the Mercury Energy NZ integration."""

import json
from pathlib import Path
from typing import Final

# Read version from manifest.json
_MANIFEST_PATH = Path(__file__).parent / "manifest.json"
with open(_MANIFEST_PATH, encoding="utf-8") as _f:
    INTEGRATION_VERSION: Final[str] = json.load(_f).get("version", "0.0.0")

DOMAIN: Final[str] = "mercury_co_nz"

# Base URL for frontend Lovelace resources (must match static path prefix)
URL_BASE: Final[str] = f"/api/{DOMAIN}"

# JavaScript modules to register as Lovelace resources (cards only; core/styles are imported by cards)
JSMODULES: Final[list[dict[str, str]]] = [
    {"name": "Mercury Energy Usage Card", "filename": "energy-usage-card.js", "version": INTEGRATION_VERSION},
    {"name": "Mercury Energy Weekly Summary Card", "filename": "energy-weekly-summary-card.js", "version": INTEGRATION_VERSION},
    {"name": "Mercury Energy Monthly Summary Card", "filename": "energy-monthly-summary-card.js", "version": INTEGRATION_VERSION},
]

# Configuration keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Default values
DEFAULT_SCAN_INTERVAL = 5  # minutes
DEFAULT_NAME = "Mercury NZ"

# Sensor types
SENSOR_TYPES = {
    "total_usage": {
        "name": "Total Usage (7 days)",
        "unit": "kWh",
        "icon": "mdi:lightning-bolt",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    "energy_usage": {
        "name": "Energy Usage",
        "unit": "kWh",
        "icon": "mdi:flash",
        "device_class": "energy",
        "state_class": "total",
    },
    "current_bill": {
        "name": "Current Bill (7 days)",
        "unit": "$",
        "icon": "mdi:currency-usd",
        "device_class": "monetary",
        "state_class": "total",
    },
    "latest_daily_usage": {
        "name": "Latest Daily Usage",
        "unit": "kWh",
        "icon": "mdi:flash-outline",
        "device_class": "energy",
        "state_class": "total",
    },
    "latest_daily_cost": {
        "name": "Latest Daily Cost",
        "unit": "$",
        "icon": "mdi:cash",
        "device_class": "monetary",
        "state_class": "total",
    },
    "average_temperature": {
        "name": "Average Temperature",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "current_temperature": {
        "name": "Current Temperature",
        "unit": "°C",
        "icon": "mdi:thermometer-lines",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "customer_id": {
        "name": "Customer ID",
        "unit": None,
        "icon": "mdi:account-circle",
        "device_class": None,
        "state_class": None,
    },
    "hourly_usage": {
        "name": "Hourly Usage (7 days)",
        "unit": "kWh",
        "icon": "mdi:clock-outline",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    "monthly_usage": {
        "name": "Monthly Usage (2 months)",
        "unit": "kWh",
        "icon": "mdi:calendar-month",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    # Bill Summary Sensors
    "bill_account_id": {
        "name": "Account Number",
        "unit": None,
        "icon": "mdi:account-details",
        "device_class": None,
        "state_class": None,
    },
    "bill_balance": {
        "name": "Current Balance",
        "unit": "$",
        "icon": "mdi:currency-usd",
        "device_class": "monetary",
        "state_class": "total",
    },
    "bill_due_amount": {
        "name": "Amount Due",
        "unit": "$",
        "icon": "mdi:currency-usd-off",
        "device_class": "monetary",
        "state_class": "total",
    },
    "bill_bill_date": {
        "name": "Bill Date",
        "unit": None,
        "icon": "mdi:calendar-check",
        "device_class": "date",
        "state_class": None,
    },
    "bill_due_date": {
        "name": "Due Date",
        "unit": None,
        "icon": "mdi:calendar-alert",
        "device_class": "date",
        "state_class": None,
    },
    "bill_overdue_amount": {
        "name": "Overdue Amount",
        "unit": "$",
        "icon": "mdi:alert-circle",
        "device_class": "monetary",
        "state_class": "total",
    },
    "bill_statement_total": {
        "name": "Bill Total",
        "unit": "$",
        "icon": "mdi:receipt",
        "device_class": "monetary",
        "state_class": "total",
    },
    "bill_electricity_amount": {
        "name": "Electricity Amount",
        "unit": "$",
        "icon": "mdi:lightning-bolt",
        "device_class": "monetary",
        "state_class": "total",
    },
    "bill_gas_amount": {
        "name": "Gas Amount",
        "unit": "$",
        "icon": "mdi:fire",
        "device_class": "monetary",
        "state_class": "total",
    },
    "bill_broadband_amount": {
        "name": "Broadband Amount",
        "unit": "$",
        "icon": "mdi:wifi",
        "device_class": "monetary",
        "state_class": "total",
    },
    "bill_payment_type": {
        "name": "Payment Type",
        "unit": None,
        "icon": "mdi:credit-card",
        "device_class": None,
        "state_class": None,
    },
    "bill_payment_method": {
        "name": "Payment Method",
        "unit": None,
        "icon": "mdi:bank",
        "device_class": None,
        "state_class": None,
    },
    # Weekly Summary Sensors
    "weekly_start_date": {
        "name": "Weekly Period Start",
        "unit": None,
        "icon": "mdi:calendar-week-begin",
        "device_class": "date",
        "state_class": None,
    },
    "weekly_end_date": {
        "name": "Weekly Period End",
        "unit": None,
        "icon": "mdi:calendar-week",
        "device_class": "date",
        "state_class": None,
    },
    "weekly_usage_cost": {
        "name": "Weekly Usage Cost",
        "unit": "$",
        "icon": "mdi:currency-usd",
        "device_class": "monetary",
        "state_class": "total",
    },
    "weekly_notes": {
        "name": "Weekly Usage Notes Count",
        "unit": "notes",
        "icon": "mdi:note-text",
        "device_class": None,
        "state_class": "measurement",
    },
    "weekly_usage_history": {
        "name": "Weekly Usage Days Count",
        "unit": "days",
        "icon": "mdi:chart-line",
        "device_class": None,
        "state_class": "measurement",
    },
    # Monthly Summary Sensors
    "monthly_billing_start_date": {
        "name": "Billing Period Start",
        "unit": None,
        "icon": "mdi:calendar-start",
        "device_class": "date",
        "state_class": None,
    },
    "monthly_billing_end_date": {
        "name": "Billing Period End",
        "unit": None,
        "icon": "mdi:calendar-end",
        "device_class": "date",
        "state_class": None,
    },
    "monthly_days_remaining": {
        "name": "Days Remaining in Period",
        "unit": "days",
        "icon": "mdi:calendar-clock",
        "device_class": None,
        "state_class": "measurement",
    },
    "monthly_usage_cost": {
        "name": "Current Period Cost",
        "unit": "$",
        "icon": "mdi:currency-usd",
        "device_class": "monetary",
        "state_class": "total",
    },
    "monthly_usage_consumption": {
        "name": "Current Period Usage",
        "unit": "kWh",
        "icon": "mdi:lightning-bolt",
        "device_class": "energy",
        "state_class": "total",
    },
    "monthly_billing_progress_percent": {
        "name": "Billing Period Progress",
        "unit": "%",
        "icon": "mdi:progress-clock",
        "device_class": None,
        "state_class": "measurement",
    },
    "monthly_projected_bill_note": {
        "name": "Projected Bill Note",
        "unit": None,
        "icon": "mdi:note-text",
        "device_class": None,
        "state_class": None,
    },
}

# API Constants
DECIMAL_PLACES = 2
TEMP_DECIMAL_PLACES = 1
FALLBACK_ZERO = 0
FALLBACK_EMPTY_LIST = []
