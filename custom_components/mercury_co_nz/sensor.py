"""Mercury Energy NZ sensor platform."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    SENSOR_TYPES,
    ICP_SCOPED_SENSOR_TYPES,
    DEFAULT_NAME,
    CONF_EMAIL,
    CHART_ATTRIBUTE_DAILY_DAYS,
    CHART_ATTRIBUTE_HOURLY_HOURS,
)
from .coordinator import MercuryDataUpdateCoordinator
from .statistics import _sanitize_for_key

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mercury Energy sensors from a config entry (v2.0.0 multi-ICP).

    Account-scoped sensors (bill_*, weekly_*, monthly_*, customer_id) get a
    single instance attached to the parent "Mercury Account" device. ICP-scoped
    sensors (defined in const.py:ICP_SCOPED_SENSOR_TYPES) get one instance per
    discovered electricity ICP — primary keeps legacy unique_id; secondary
    ICPs get ICP-token-prefixed entity_ids.
    """
    coordinator: MercuryDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # If first-cycle ICP discovery hasn't completed, raise ConfigEntryNotReady
    # so HA retries setup automatically. Avoids "no devices appear until manual
    # restart" UX gap.
    if not coordinator._discovered and not coordinator.last_update_success:
        raise ConfigEntryNotReady(
            "Mercury CO NZ: ICP discovery not yet complete; HA will retry"
        )

    name = config_entry.data.get(CONF_NAME, DEFAULT_NAME)
    email = config_entry.data[CONF_EMAIL]
    entities: list[MercurySensor] = []

    # Account-scoped sensors — single instance per account, attached to parent device
    for sensor_type in SENSOR_TYPES:
        if sensor_type in ICP_SCOPED_SENSOR_TYPES:
            continue
        entities.append(
            MercurySensor(
                coordinator, sensor_type, name, email,
                service_id=None, is_primary=True, fuel_type=None,
            )
        )

    # ICP-scoped sensors — one instance per electricity ICP × ICP-scoped types
    for service in coordinator._discovered_electricity_services:
        is_primary = service.service_id == coordinator._primary_service_id
        for sensor_type in ICP_SCOPED_SENSOR_TYPES:
            entities.append(
                MercurySensor(
                    coordinator, sensor_type, name, email,
                    service_id=service.service_id,
                    is_primary=is_primary,
                    fuel_type="electricity",
                )
            )

    async_add_entities(entities)
    _LOGGER.info(
        "Mercury CO NZ: registered %d entities (account-scoped: %d, ICP-scoped: %d × %d ICPs)",
        len(entities),
        len(SENSOR_TYPES) - len(ICP_SCOPED_SENSOR_TYPES),
        len(ICP_SCOPED_SENSOR_TYPES),
        len(coordinator._discovered_electricity_services),
    )


class MercurySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Mercury Energy sensor."""

    # v1.6.1: Tell HA to compose friendly_name as `{device.name} {entity.name}`
    # automatically. Together with `_attr_name = sensor_config["name"]` and
    # `device_info["name"] = self._device_display_name` below, this produces
    # clean entity_ids like `sensor.mercury_nz_gas_monthly_usage` instead of
    # the v1.6.0 form `sensor.mercury_nz_<email-slug>_mercury_nz_gas_monthly_usage`
    # that recent HA versions generate when has_entity_name is False AND
    # `_attr_name` repeats the device-name prefix.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MercuryDataUpdateCoordinator,
        sensor_type: str,
        name: str,
        email: str,
        service_id: str | None = None,
        is_primary: bool = True,
        fuel_type: str | None = None,
    ) -> None:
        """Initialize the sensor.

        v2.0.0: ICP-scoped sensors are scoped to a service_id (with is_primary
        controlling whether the legacy unique_id is preserved). Account-scoped
        sensors pass service_id=None and attach to the parent device.

        Default args (service_id=None, is_primary=True, fuel_type=None) produce
        byte-identical unique_id to v1.5.x — back-compat for primary-ICP sensors.
        """
        super().__init__(coordinator)

        self._sensor_type = sensor_type
        self._email = email
        self._service_id = service_id
        self._is_primary = is_primary
        self._fuel_type = fuel_type
        # The config-entry name (e.g. "Mercury NZ", or a user-customized
        # "Holiday House"). Used for the device's display name so multi-account
        # users can still distinguish their Mercury devices in the UI.
        self._device_display_name = name

        # Validate sensor type exists in configuration
        if sensor_type not in SENSOR_TYPES:
            _LOGGER.error("❌ Sensor type '%s' not found in SENSOR_TYPES", sensor_type)
            raise ValueError(f"Unknown sensor type: {sensor_type}")

        sensor_config = SENSOR_TYPES[sensor_type]
        # Use a hash of email for unique_id to handle special characters.
        import hashlib
        email_hash = hashlib.md5(email.encode()).hexdigest()[:8]

        # LOAD-BEARING back-compat: primary-ICP OR account-scoped → legacy unique_id.
        # Single-ICP existing users see byte-identical entity_id to v1.5.x for
        # entities registered before v1.6.1. v1.6.1's _attr_has_entity_name
        # pattern means HA composes friendly_name as `{device.name} {_attr_name}`
        # automatically — so `_attr_name` is just the per-sensor suffix here,
        # not the doubled "Mercury NZ Foo" form. Secondary ICPs include the
        # service_id in `_attr_name` so the friendly_name distinguishes them
        # from primary on the same account.
        if service_id is None or is_primary:
            self._attr_name = sensor_config["name"]
            self._attr_unique_id = f"{email_hash}_{sensor_type}"
        else:
            icp_token = _sanitize_for_key(service_id)
            self._attr_name = f"{service_id} {sensor_config['name']}"
            self._attr_unique_id = f"{email_hash}_{icp_token}_{sensor_type}"

        self._attr_native_unit_of_measurement = sensor_config["unit"]
        self._attr_icon = sensor_config["icon"]
        self._attr_device_class = sensor_config.get("device_class")
        self._attr_state_class = sensor_config.get("state_class")

    @property
    def device_info(self):
        """Return device information.

        v2.0.0 + v1.6.1: account-scoped sensors attach to the parent device
        (one per email); ICP-scoped sensors attach to per-ICP child devices
        linked via `via_device`. Neither device.name includes the user's
        email anymore — HA's entity_id slug pulled the email into every
        new entity in v1.6.0 era. Multi-account users are still uniquely
        keyed by the `(DOMAIN, email)` identifier tuple; only the displayed
        name simplifies.
        """
        if self._service_id is None:
            # Account-scoped — parent device
            return {
                "identifiers": {(DOMAIN, self._email)},
                "name": self._device_display_name,
                "manufacturer": "Mercury Energy",
                "model": "Account",
            }
        # ICP-scoped — child device with via_device parent
        return {
            "identifiers": {(DOMAIN, f"{self._email}_{self._service_id}")},
            "name": (
                f"ICP {self._service_id}"
                + (
                    f" ({self._fuel_type})"
                    if self._fuel_type and self._fuel_type != "electricity"
                    else ""
                )
                + (" (primary)" if self._is_primary else "")
            ),
            "manufacturer": "Mercury Energy",
            "model": f"{(self._fuel_type or 'electricity').title()} Meter",
            "via_device": (DOMAIN, self._email),
        }

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this entity."""
        # Always return the unit from configuration to ensure consistency
        sensor_config = SENSOR_TYPES.get(self._sensor_type, {})
        config_unit = sensor_config.get("unit")

        # Force update the stored value to ensure consistency
        self._attr_native_unit_of_measurement = config_unit

        return config_unit

    @property
    def unit_of_measurement(self):
        """Legacy property for backward compatibility."""
        return self.native_unit_of_measurement

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return True

    @property
    def available(self):
        """Return True if entity is available."""
        # Always consider sensors available, even if coordinator data is None
        # This prevents unit inconsistency warnings during startup
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            _LOGGER.debug("🔍 Sensor %s: No coordinator data available, using default", self._sensor_type)
            # Return appropriate default based on sensor unit to maintain consistency
            sensor_config = SENSOR_TYPES.get(self._sensor_type, {})
            unit = sensor_config.get("unit")
            if unit in ["kWh", "$", "°C", "days", "%"]:
                return 0
            else:
                return None

        # v2.0.0: ICP-scoped non-primary sensors read from icp_<token>_<key>
        # in coordinator.data. Account-scoped or primary-ICP sensors read
        # from top-level keys (back-compat with v1.5.x).
        if (
            self._service_id is not None
            and not self._is_primary
            and self._sensor_type in ICP_SCOPED_SENSOR_TYPES
        ):
            icp_token = _sanitize_for_key(self._service_id)
            raw_value = self.coordinator.data.get(f"icp_{icp_token}_{self._sensor_type}")
        else:
            raw_value = self.coordinator.data.get(self._sensor_type)
        _LOGGER.debug("🔍 Sensor %s: Raw value = %s (type: %s)", self._sensor_type, raw_value, type(raw_value))

        # If raw_value is None, log for debugging and return appropriate default
        if raw_value is None:
            # For sensors with units, return 0 instead of None to maintain unit consistency
            sensor_config = SENSOR_TYPES.get(self._sensor_type, {})
            unit = sensor_config.get("unit")

            if unit in ["kWh", "$", "°C", "days", "%"]:
                # Return 0 for numeric sensors to maintain unit consistency
                _LOGGER.warning("🔧 Sensor %s (unit: %s) has None value, returning 0. Entity unit: %s. Available keys: %s",
                              self._sensor_type, unit, self._attr_native_unit_of_measurement,
                              list(self.coordinator.data.keys())[:10])

                # Additional debugging: categorize the available keys to help diagnose the issue
                if self.coordinator.data:
                    available_keys = list(self.coordinator.data.keys())
                    bill_keys = [k for k in available_keys if k.startswith('bill_')]
                    monthly_keys = [k for k in available_keys if k.startswith('monthly_')]
                    content_keys = [k for k in available_keys if k.startswith('content_')]
                    usage_keys = [k for k in available_keys if not k.startswith(('bill_', 'monthly_', 'content_'))]

                    _LOGGER.info("🔍 Data analysis for sensor %s:", self._sensor_type)
                    _LOGGER.info("   📊 Usage keys (%d): %s", len(usage_keys), usage_keys[:5])
                    _LOGGER.info("   💳 Bill keys (%d): %s", len(bill_keys), bill_keys[:5])
                    _LOGGER.info("   📅 Monthly keys (%d): %s", len(monthly_keys), monthly_keys[:3])
                    _LOGGER.info("   📄 Content keys (%d): %s", len(content_keys), content_keys[:3])

                    if not usage_keys and self._sensor_type in ['total_usage', 'energy_usage', 'current_bill', 'latest_daily_usage', 'latest_daily_cost', 'average_temperature', 'current_temperature', 'hourly_usage', 'monthly_usage']:
                        _LOGGER.error("❌ DIAGNOSIS: Usage API call failed - no usage data keys found in coordinator data")
                        _LOGGER.error("❌ This means get_usage_data() returned empty or failed")

                return 0
            else:
                # Return None for sensors without units (text sensors, etc.)
                _LOGGER.debug("Sensor %s (no unit) has None value, returning None", self._sensor_type)
                return None

        # Handle complex data types that shouldn't be sensor states
        if self._sensor_type in ["weekly_usage_history", "weekly_notes"]:
            # For complex data that should be in attributes only, return a simple state
            if self._sensor_type == "weekly_usage_history":
                if isinstance(raw_value, list) and len(raw_value) > 0:
                    return len(raw_value)  # Return the count of days
                else:
                    return 0
            elif self._sensor_type == "weekly_notes":
                if isinstance(raw_value, list) and len(raw_value) > 0:
                    return len(raw_value)  # Return the count of notes
                else:
                    return 0

        # Handle date conversion for date sensors (including weekly dates)
        if (self._sensor_type in ["due_date", "bill_due_date", "bill_bill_date", "monthly_billing_start_date", "monthly_billing_end_date", "weekly_start_date", "weekly_end_date"] and
            raw_value is not None):
            try:
                _LOGGER.debug("....... Processing date sensor %s with raw value: %s (type: %s)", self._sensor_type, repr(raw_value), type(raw_value))

                # If it's already a date object, return it
                if hasattr(raw_value, 'date') and callable(getattr(raw_value, 'date')):
                    date_result = raw_value.date()
                    _LOGGER.debug("... Converted datetime to date: %s -> %s", raw_value, date_result)
                    return date_result
                elif hasattr(raw_value, 'year') and hasattr(raw_value, 'month') and hasattr(raw_value, 'day'):
                    # It's already a date object
                    _LOGGER.debug("... Already a date object: %s", raw_value)
                    return raw_value
                elif isinstance(raw_value, str) and raw_value.strip():
                    # Parse string date
                    raw_value = raw_value.strip()
                    if 'T' in raw_value:
                        # Handle ISO datetime format
                        dt = datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
                        date_result = dt.date()  # Return just the date part
                        _LOGGER.debug("... Parsed ISO datetime %s -> %s", raw_value, date_result)
                        return date_result
                    else:
                        # Handle date-only format
                        dt = datetime.strptime(raw_value, '%Y-%m-%d')
                        date_result = dt.date()
                        _LOGGER.debug("... Parsed date string %s -> %s", raw_value, date_result)
                        return date_result
                else:
                    _LOGGER.warning("...... Unexpected date value format for %s: %s", self._sensor_type, repr(raw_value))
                    return None
            except (ValueError, AttributeError) as e:
                # If parsing fails, return None to avoid errors
                _LOGGER.error("... Date parsing failed for %s with value %s: %s", self._sensor_type, repr(raw_value), e)
                return None

        return raw_value

    @property
    def extra_state_attributes(self):
        """Return additional state attributes for graphing."""
        if not self.coordinator.data:
            return {}

        attributes = {}

        # Define sensors that should get full historical data for charting
        # Only these sensors need the large datasets - others get minimal attributes
        CHART_DATA_SENSORS = [
            "energy_usage",      # Main energy usage sensor - primary chart sensor
            "total_usage",       # Total usage sensor
            "current_bill"       # Current bill sensor
        ]

        # Only add large historical datasets to chart-capable sensors.
        # Issue #4: HA recorder caps state_attributes at 16384 bytes; oversize
        # attrs are DROPPED (not truncated), causing unit_of_measurement to be
        # lost downstream. Truncate the chart history lists to fit ~14KB.
        # Full 180-day history is preserved in coordinator.data + the JSON
        # files for the statistics importer (Energy Dashboard).
        if self._sensor_type in CHART_DATA_SENSORS:
            # Daily usage history — explicit if/elif so data_source label is
            # never mislabelled if extended key exists but holds an empty list.
            daily_source = None
            if self.coordinator.data.get("extended_daily_usage_history"):
                daily_source = self.coordinator.data["extended_daily_usage_history"]
                attributes["data_source"] = "mercury_energy_api_extended"
                _LOGGER.debug(
                    "Using extended daily usage history: %d days (truncating to last %d for attributes)",
                    len(daily_source), CHART_ATTRIBUTE_DAILY_DAYS,
                )
            elif self.coordinator.data.get("daily_usage_history"):
                daily_source = self.coordinator.data["daily_usage_history"]
                attributes["data_source"] = "mercury_energy_api"
            if daily_source:
                attributes["daily_usage_history"] = daily_source[-CHART_ATTRIBUTE_DAILY_DAYS:]

            # Temperature — drop `temperature_history` (unused by the card; verified
            # by grep — only `recent_temperatures` is consumed). Truncate the
            # simplified `recent_temperatures` to match daily window.
            temp_source = None
            if self.coordinator.data.get("extended_temperature_history"):
                temp_source = self.coordinator.data["extended_temperature_history"]
            elif self.coordinator.data.get("temperature_history"):
                temp_source = self.coordinator.data["temperature_history"]
            if temp_source:
                truncated_temps = temp_source[-CHART_ATTRIBUTE_DAILY_DAYS:]
                attributes["recent_temperatures"] = [
                    {
                        "date": day.get("date", "").split("T")[0],
                        "temperature": day.get("temp", 0),
                    }
                    for day in truncated_temps
                ]

            # Hourly usage history — same explicit if/elif pattern as daily.
            hourly_source = None
            if self.coordinator.data.get("extended_hourly_usage_history"):
                hourly_source = self.coordinator.data["extended_hourly_usage_history"]
                attributes["data_source_hourly"] = "mercury_energy_api_extended"
                _LOGGER.debug(
                    "Using extended hourly usage history: %d hours (truncating to last %d for attributes)",
                    len(hourly_source), CHART_ATTRIBUTE_HOURLY_HOURS,
                )
            elif self.coordinator.data.get("hourly_usage_history"):
                hourly_source = self.coordinator.data["hourly_usage_history"]
                attributes["data_source_hourly"] = "mercury_energy_api"
            if hourly_source:
                attributes["hourly_usage_history"] = hourly_source[-CHART_ATTRIBUTE_HOURLY_HOURS:]

            # Monthly usage history — small (~1KB), unchanged.
            if "monthly_usage_history" in self.coordinator.data:
                monthly_history = self.coordinator.data["monthly_usage_history"]
                attributes["monthly_usage_history"] = monthly_history
                attributes["monthly_data_points"] = len(monthly_history)

        # Gas chart history — sibling to (not inside) the electricity
        # CHART_DATA_SENSORS block so the gas sensor doesn't inherit
        # electricity history attributes that would push it toward the 14KB
        # cap (Issue #4). Each entry in gas_monthly_usage_history carries
        # `is_estimated`/`read_type` tags from pymercury's consumption_periods
        # (1.1.3+) which gas-monthly-summary-card.js uses to color bars
        # (yellow=actual, gray=estimated).
        if self._sensor_type == "gas_monthly_usage":
            gas_history = self.coordinator.data.get("gas_monthly_usage_history") or []
            attributes["gas_monthly_usage_history"] = gas_history
            attributes["gas_monthly_data_points"] = len(gas_history)
            attributes["gas_monthly_total_usage"] = (
                self.coordinator.data.get("gas_monthly_usage") or 0
            )
            attributes["gas_monthly_total_cost"] = (
                self.coordinator.data.get("gas_monthly_cost") or 0
            )

        # Add bill statement details for all sensors (if available)
        if "bill_statement_details" in self.coordinator.data:
            attributes["bill_statement_details"] = self.coordinator.data["bill_statement_details"]

                # Add monthly summary attributes for all sensors (needed for monthly summary card)
        monthly_attributes = [
            "monthly_usage_cost", "monthly_usage_consumption", "monthly_days_remaining",
            "monthly_billing_start_date", "monthly_billing_end_date",
            "monthly_billing_progress_percent", "monthly_projected_bill_note"
        ]

        for attr in monthly_attributes:
            if attr in self.coordinator.data:
                attributes[attr] = self.coordinator.data[attr]

        # Add weekly summary attributes for all sensors (needed for weekly summary card)
        weekly_attributes = [
            "weekly_usage_cost", "weekly_start_date", "weekly_end_date",
            "weekly_notes", "weekly_usage_history"
        ]

        for attr in weekly_attributes:
            if attr in self.coordinator.data:
                attributes[attr] = self.coordinator.data[attr]

        # Add content attributes for all sensors (needed for monthly summary card disclaimers)
        content_attributes = [
            "content_disclaimer_text", "content_monthly_summary_description"
        ]

        for attr in content_attributes:
            if attr in self.coordinator.data:
                attributes[attr] = self.coordinator.data[attr]

        # Add common attributes for all sensors
        if "last_updated" in self.coordinator.data:
            attributes["last_updated"] = self.coordinator.data["last_updated"]

        # Add formatted New Zealand dates for date sensors
        if self._sensor_type in ["due_date", "bill_due_date", "bill_bill_date", "monthly_billing_start_date", "monthly_billing_end_date", "weekly_start_date", "weekly_end_date"]:
            raw_value = self.coordinator.data.get(self._sensor_type)
            if raw_value:
                try:
                    from datetime import datetime
                    # Parse the date if it's a string
                    if isinstance(raw_value, str) and raw_value.strip():
                        if 'T' in raw_value:
                            # ISO datetime format
                            date_obj = datetime.fromisoformat(raw_value.replace('Z', '+00:00')).date()
                        else:
                            # Simple date format
                            date_obj = datetime.strptime(raw_value, '%Y-%m-%d').date()
                    elif hasattr(raw_value, 'date') and callable(getattr(raw_value, 'date')):
                        # datetime object
                        date_obj = raw_value.date()
                    elif hasattr(raw_value, 'year'):
                        # Already a date object
                        date_obj = raw_value
                    else:
                        date_obj = None

                    if date_obj:
                        # Format as "DD MMM YYYY" for New Zealand
                        nz_formatted = date_obj.strftime("%d %b %Y")
                        attributes["formatted_date"] = nz_formatted
                        attributes["date_nz_format"] = nz_formatted
                except Exception:
                    pass  # If date parsing fails, skip formatting

        return attributes
