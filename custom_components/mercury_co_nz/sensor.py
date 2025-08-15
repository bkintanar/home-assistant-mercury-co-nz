"""Mercury Energy NZ sensor platform."""
from __future__ import annotations

import logging
from datetime import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_TYPES, DEFAULT_NAME, CONF_EMAIL
from .coordinator import MercuryDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mercury Energy sensors from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    for sensor_type in SENSOR_TYPES:
        entities.append(
            MercurySensor(
                coordinator,
                sensor_type,
                config_entry.data.get(CONF_NAME, DEFAULT_NAME),
                config_entry.data[CONF_EMAIL],
            )
        )

    async_add_entities(entities)


class MercurySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Mercury Energy sensor."""

    def __init__(
        self,
        coordinator: MercuryDataUpdateCoordinator,
        sensor_type: str,
        name: str,
        email: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._sensor_type = sensor_type
        self._email = email

        # Validate sensor type exists in configuration
        if sensor_type not in SENSOR_TYPES:
            _LOGGER.error("❌ Sensor type '%s' not found in SENSOR_TYPES", sensor_type)
            raise ValueError(f"Unknown sensor type: {sensor_type}")

        sensor_config = SENSOR_TYPES[sensor_type]
        _LOGGER.debug("🔧 Initializing sensor '%s' with config: %s", sensor_type, sensor_config)

        self._attr_name = f"{name} {sensor_config['name']}"
        # Use a hash of email for unique_id to handle special characters
        import hashlib
        email_hash = hashlib.md5(email.encode()).hexdigest()[:8]
        self._attr_unique_id = f"{email_hash}_{sensor_type}"

        # Force unit assignment to ensure consistency
        self._attr_native_unit_of_measurement = sensor_config["unit"]

        self._attr_icon = sensor_config["icon"]
        self._attr_device_class = sensor_config.get("device_class")
        self._attr_state_class = sensor_config.get("state_class")

        _LOGGER.debug("📊 Sensor '%s' initialized with unit: %s, device_class: %s, state_class: %s",
                     sensor_type, self._attr_native_unit_of_measurement,
                     self._attr_device_class, self._attr_state_class)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._email)},
            "name": f"Mercury NZ - {self._email}",
            "manufacturer": "Mercury Energy",
            "model": "Energy Monitor",
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
                return 0
            else:
                # Return None for sensors without units (text sensors, etc.)
                _LOGGER.debug("Sensor %s (no unit) has None value, returning None", self._sensor_type)
                return None

        # Handle date conversion for date sensors
        if (self._sensor_type in ["due_date", "bill_due_date", "bill_bill_date", "monthly_billing_start_date", "monthly_billing_end_date"] and
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

        # Only add large historical datasets to chart-capable sensors
        if self._sensor_type in CHART_DATA_SENSORS:
            # Add detailed time-series data for graphing
            # Use extended historical data if available (cumulative), fallback to current data
            if "extended_daily_usage_history" in self.coordinator.data:
                daily_history = self.coordinator.data["extended_daily_usage_history"]
                attributes["data_source"] = "mercury_energy_api_extended"
                _LOGGER.debug("Using extended daily usage history: %d days", len(daily_history))
            elif "daily_usage_history" in self.coordinator.data:
                daily_history = self.coordinator.data["daily_usage_history"]
                attributes["data_source"] = "mercury_energy_api"

            if "daily_usage_history" in self.coordinator.data or "extended_daily_usage_history" in self.coordinator.data:
                # Store the full daily usage history for graphing
                attributes["daily_usage_history"] = daily_history
            else:
                # Also add a simplified version for easier access
                attributes["recent_usage"] = [
                    {
                        "date": day.get("date", "").split("T")[0],  # Just the date part
                        "consumption": day.get("consumption", 0),
                        "cost": day.get("cost", 0)
                    }
                    for day in daily_history
                ]
                attributes["period_days"] = len(daily_history)

                # Add metadata about historical data
                if "total_historical_days" in self.coordinator.data:
                    attributes["total_historical_days"] = self.coordinator.data["total_historical_days"]

            # Add temperature history for chart sensors (if available)
            # Use extended temperature data if available (cumulative), fallback to current data
            if "extended_temperature_history" in self.coordinator.data:
                temp_history = self.coordinator.data["extended_temperature_history"]
                _LOGGER.debug("Using extended temperature history: %d days", len(temp_history))
            elif "temperature_history" in self.coordinator.data:
                temp_history = self.coordinator.data["temperature_history"]

            if "temperature_history" in self.coordinator.data or "extended_temperature_history" in self.coordinator.data:
                # Store the full temperature history for graphing
                attributes["temperature_history"] = temp_history

                # Also add a simplified version for easier access
                attributes["recent_temperatures"] = [
                    {
                        "date": day.get("date", "").split("T")[0],
                        "temperature": day.get("temp", 0)
                    }
                    for day in temp_history
                ]

            # Add hourly usage history for chart sensors (if available)
            # Use extended hourly data if available (cumulative), fallback to current data
            if "extended_hourly_usage_history" in self.coordinator.data:
                hourly_history = self.coordinator.data["extended_hourly_usage_history"]
                attributes["data_source_hourly"] = "mercury_energy_api_extended"
                _LOGGER.debug("Using extended hourly usage history: %d hours", len(hourly_history))
            elif "hourly_usage_history" in self.coordinator.data:
                hourly_history = self.coordinator.data["hourly_usage_history"]
                attributes["data_source_hourly"] = "mercury_energy_api"

            if "hourly_usage_history" in self.coordinator.data or "extended_hourly_usage_history" in self.coordinator.data:
                # Store the full hourly usage history for graphing
                attributes["hourly_usage_history"] = hourly_history
            else:
                # Also add metadata
                attributes["hourly_data_points"] = len(hourly_history)

                # Add metadata about historical hourly data
                if "total_historical_hours" in self.coordinator.data:
                    attributes["total_historical_hours"] = self.coordinator.data["total_historical_hours"]

            # Add monthly usage history for chart sensors (if available)
            if "monthly_usage_history" in self.coordinator.data:
                monthly_history = self.coordinator.data["monthly_usage_history"]

                # Store the full monthly usage history for graphing
                attributes["monthly_usage_history"] = monthly_history

                # Also add metadata
                attributes["monthly_data_points"] = len(monthly_history)



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
        if self._sensor_type in ["due_date", "bill_due_date", "bill_bill_date", "monthly_billing_start_date", "monthly_billing_end_date"]:
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
