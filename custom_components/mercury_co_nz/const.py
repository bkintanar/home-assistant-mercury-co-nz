"""Constants for the Mercury Energy NZ integration."""

DOMAIN = "mercury_co_nz"

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
}
