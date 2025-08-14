"""Data update coordinator for Mercury Energy NZ."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_EMAIL
from .mercury_api import MercuryAPI

_LOGGER = logging.getLogger(__name__)


class MercuryDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Mercury Energy API."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        update_interval: timedelta,
    ) -> None:
        """Initialize."""
        self.api = MercuryAPI(
            async_get_clientsession(hass),
            config[CONF_EMAIL],
            config[CONF_PASSWORD],
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        _LOGGER.info("Mercury coordinator: Starting data update")
        try:
            # Fetch both usage data and bill summary data
            _LOGGER.info("📊 Fetching usage data...")
            usage_data = await self.api.get_usage_data()
            _LOGGER.info("Mercury coordinator: Received usage data")

            _LOGGER.info("💳 Fetching bill summary data...")
            bill_data = await self.api.get_bill_summary()
            _LOGGER.info("Mercury coordinator: Received bill data")

            # Combine both datasets
            combined_data = usage_data.copy() if usage_data else {}
            if bill_data:
                # Add bill data with prefix to avoid naming conflicts
                for key, value in bill_data.items():
                    combined_data[f"bill_{key}"] = value

            _LOGGER.info("Mercury coordinator: Combined data keys: %s", list(combined_data.keys()))

            # Log the amount of fresh data we received
            daily_data_count = len(combined_data.get('daily_usage_history', []))
            temp_data_count = len(combined_data.get('temperature_history', []))
            hourly_data_count = len(combined_data.get('hourly_usage_history', []))
            _LOGGER.info("📊 Fresh API data: %d days usage, %d days temperature, %d hours hourly",
                        daily_data_count, temp_data_count, hourly_data_count)

            # 🎯 Store daily data in JSON file for dynamic graphs (this accumulates historical data)
            await self._store_daily_data_json(combined_data)

            # 🕐 Store hourly data in JSON file for 7-day history (this accumulates historical data)
            await self._store_hourly_data_json(combined_data)

            # Load extended historical data to expose via sensors (cumulative from JSON file)
            extended_data = await self._load_extended_historical_data()
            if extended_data:
                # Update the combined data with extended history (accumulated over time)
                combined_data.update(extended_data)
                extended_usage_count = len(extended_data.get('extended_daily_usage_history', []))
                extended_temp_count = len(extended_data.get('extended_temperature_history', []))
                _LOGGER.info("📈 Enhanced with cumulative historical data: %d days usage, %d days temperature",
                           extended_usage_count, extended_temp_count)

                # Log date range if we have data
                if extended_data.get('extended_daily_usage_history'):
                    first_date = extended_data['extended_daily_usage_history'][0].get('date', 'Unknown')
                    last_date = extended_data['extended_daily_usage_history'][-1].get('date', 'Unknown')
                    _LOGGER.info("📅 Historical data range: %s to %s", first_date, last_date)

            # Load extended hourly data to expose via sensors (cumulative from JSON file)
            extended_hourly_data = await self._load_extended_hourly_data()
            if extended_hourly_data:
                # Update the combined data with extended hourly history (accumulated over time)
                combined_data.update(extended_hourly_data)
                extended_hourly_count = len(extended_hourly_data.get('extended_hourly_usage_history', []))
                _LOGGER.info("🕐 Enhanced with cumulative hourly data: %d hours",
                           extended_hourly_count)

                # Log datetime range if we have hourly data
                if extended_hourly_data.get('extended_hourly_usage_history'):
                    first_datetime = extended_hourly_data['extended_hourly_usage_history'][0].get('datetime', 'Unknown')
                    last_datetime = extended_hourly_data['extended_hourly_usage_history'][-1].get('datetime', 'Unknown')
                    _LOGGER.info("🕐 Hourly data range: %s to %s", first_datetime, last_datetime)

            return combined_data
        except Exception as exception:
            _LOGGER.error("Mercury coordinator: Error communicating with API: %s", exception)
            raise UpdateFailed(f"Error communicating with API: {exception}") from exception

    async def _store_hourly_data_json(self, data: dict[str, Any]) -> None:
        """Store cumulative hourly usage data in JSON file for 7-day history."""
        if not data or 'hourly_usage_history' not in data:
            _LOGGER.debug("No hourly usage history to store")
            return

        try:
            # Create www directory if it doesn't exist
            www_dir = os.path.join(self.hass.config.config_dir, "www")

            def ensure_www_dir():
                os.makedirs(www_dir, exist_ok=True)

            await asyncio.get_event_loop().run_in_executor(None, ensure_www_dir)

            json_file = os.path.join(www_dir, "mercury_hourly.json")

            # Load existing hourly data to preserve history beyond what API provides
            existing_hourly_data = {}

            def load_existing_hourly_data():
                if os.path.exists(json_file):
                    try:
                        with open(json_file, 'r') as f:
                            existing_json = json.load(f)
                            return existing_json.get('hourly_usage', {})
                    except Exception as e:
                        _LOGGER.warning("Could not load existing hourly data: %s", e)
                return {}

            existing_hourly_data = await asyncio.get_event_loop().run_in_executor(None, load_existing_hourly_data)

            # Merge new data with existing data (new data takes precedence)
            hourly_data = existing_hourly_data.copy()  # Start with existing

            # Add/update with new hourly data from Mercury API
            for hour in data['hourly_usage_history']:
                # Create a unique key for each hour (datetime as string)
                datetime_key = hour.get('datetime', hour.get('date', ''))
                if datetime_key:
                    hour_info = {
                        "datetime": datetime_key,
                        "consumption": float(hour.get('consumption', 0)),
                        "cost": float(hour.get('cost', 0)),
                        "timestamp": datetime_key
                    }
                    hourly_data[datetime_key] = hour_info  # This will overwrite if datetime exists

            # Keep last 7 days (168 hours) to prevent unlimited growth
            # Use UTC time for consistent timezone handling
            now_utc = datetime.now(timezone.utc)
            cutoff_time = now_utc - timedelta(days=7)

                        # Filter to keep only last 7 days
            filtered_hourly_data = {}
            for datetime_key, hour_info in hourly_data.items():
                try:
                    # Parse datetime and ensure it's UTC for comparison
                    hour_datetime = datetime.fromisoformat(datetime_key.replace('Z', '+00:00'))
                    # If the datetime is naive (no timezone), assume it's UTC
                    if hour_datetime.tzinfo is None:
                        hour_datetime = hour_datetime.replace(tzinfo=timezone.utc)

                    if hour_datetime >= cutoff_time:
                        filtered_hourly_data[datetime_key] = hour_info
                except (ValueError, AttributeError):
                    # Keep entries that can't be parsed to avoid data loss
                    filtered_hourly_data[datetime_key] = hour_info

            hourly_data = filtered_hourly_data

            if len(existing_hourly_data) != len(hourly_data):
                _LOGGER.info("Trimmed hourly data to last 7 days (was %d hours, now %d hours)",
                           len(existing_hourly_data), len(hourly_data))

            # Create sorted hourly_list for graphs
            hourly_list = [hourly_data[datetime_key] for datetime_key in sorted(hourly_data.keys())]

            # Calculate summary statistics
            total_consumption = sum(hour['consumption'] for hour in hourly_list)
            total_cost = sum(hour['cost'] for hour in hourly_list)
            num_hours = len(hourly_list)

            # Create complete JSON structure
            json_data = {
                "last_updated": datetime.now().isoformat(),
                "summary": {
                    "total_hours": num_hours,
                    "total_consumption": round(total_consumption, 2),
                    "total_cost": round(total_cost, 2),
                    "average_hourly_consumption": round(total_consumption / num_hours if num_hours > 0 else 0, 3),
                    "average_hourly_cost": round(total_cost / num_hours if num_hours > 0 else 0, 3),
                    "datetime_range": {
                        "start": hourly_list[0]['datetime'] if hourly_list else None,
                        "end": hourly_list[-1]['datetime'] if hourly_list else None
                    }
                },
                "hourly_usage": hourly_data,
                "hourly_list": sorted(hourly_list, key=lambda x: x['datetime']),  # Sorted for graphs
                "meta": {
                    "source": "mercury_energy_api",
                    "integration": "mercury_co_nz",
                    "retention_days": 7,
                    "retention_hours": 168,
                    "endpoint": "http://localhost:8123/local/mercury_hourly.json"
                }
            }

            # Write JSON file
            def write_json():
                with open(json_file, 'w') as f:
                    json.dump(json_data, f, indent=2, ensure_ascii=False)

            await asyncio.get_event_loop().run_in_executor(None, write_json)

            _LOGGER.info("✅ Stored hourly data in JSON: %d hours, %.2f kWh total (7-day retention)",
                        num_hours, total_consumption)
            _LOGGER.debug("JSON endpoint available at: http://localhost:8123/local/mercury_hourly.json")

        except Exception as e:
            _LOGGER.error("❌ Failed to store hourly data JSON: %s", e)

    async def _store_daily_data_json(self, data: dict[str, Any]) -> None:
        """Store cumulative daily usage data in JSON file for dynamic graphs."""
        if not data or 'daily_usage_history' not in data:
            _LOGGER.debug("No daily usage history to store")
            return

        try:
            # Create www directory if it doesn't exist
            www_dir = os.path.join(self.hass.config.config_dir, "www")

            def ensure_www_dir():
                os.makedirs(www_dir, exist_ok=True)

            await asyncio.get_event_loop().run_in_executor(None, ensure_www_dir)

            json_file = os.path.join(www_dir, "mercury_daily.json")

            # Load existing data to preserve history beyond 14 days
            existing_daily_data = {}
            existing_temp_data = {}

            def load_existing_data():
                if os.path.exists(json_file):
                    try:
                        with open(json_file, 'r') as f:
                            existing_json = json.load(f)
                            return existing_json.get('daily_usage', {}), existing_json.get('temperature', {})
                    except Exception as e:
                        _LOGGER.warning("Could not load existing data: %s", e)
                return {}, {}

            existing_daily_data, existing_temp_data = await asyncio.get_event_loop().run_in_executor(None, load_existing_data)

            # Merge new data with existing data (new data takes precedence)
            daily_data = existing_daily_data.copy()  # Start with existing

            # Add/update with new data from Mercury API (last 14 days)
            for day in data['daily_usage_history']:
                date_key = day['date'][:10]  # Extract YYYY-MM-DD
                day_info = {
                    "date": date_key,
                    "consumption": float(day['consumption']),
                    "cost": float(day['cost']),
                    "timestamp": day['date'],
                    "free_power": day.get('free_power', False)
                }
                daily_data[date_key] = day_info  # This will overwrite if date exists

            # Keep last 180 days (6 months) to prevent unlimited growth
            # Sort by date and keep the most recent 180 days
            sorted_dates = sorted(daily_data.keys(), reverse=True)  # Most recent first
            if len(sorted_dates) > 180:
                dates_to_keep = sorted_dates[:180]
                daily_data = {date: daily_data[date] for date in dates_to_keep}
                _LOGGER.info("Trimmed usage history to last 180 days (was %d days)", len(sorted_dates))

            # Create sorted daily_list for graphs
            daily_list = [daily_data[date] for date in sorted(daily_data.keys())]

            # Merge temperature data with existing (cumulative)
            temperature_data = existing_temp_data.copy()  # Start with existing

            if 'temperature_history' in data:
                for temp in data['temperature_history']:
                    date_key = temp['date'][:10]
                    temperature_data[date_key] = {
                        "date": date_key,
                        "temperature": temp['temp'],
                        "timestamp": temp['date']
                    }

                # Also trim temperature data to last 180 days
                sorted_temp_dates = sorted(temperature_data.keys(), reverse=True)
                if len(sorted_temp_dates) > 180:
                    temp_dates_to_keep = sorted_temp_dates[:180]
                    temperature_data = {date: temperature_data[date] for date in temp_dates_to_keep}

            # Calculate summary statistics
            total_consumption = sum(day['consumption'] for day in daily_list)
            total_cost = sum(day['cost'] for day in daily_list)
            num_days = len(daily_list)

            # Create complete JSON structure
            json_data = {
                "last_updated": datetime.now().isoformat(),
                "summary": {
                    "total_days": num_days,
                    "total_consumption": round(total_consumption, 2),
                    "total_cost": round(total_cost, 2),
                    "average_daily_consumption": round(total_consumption / num_days if num_days > 0 else 0, 2),
                    "average_daily_cost": round(total_cost / num_days if num_days > 0 else 0, 2),
                    "cost_per_kwh": round(total_cost / total_consumption if total_consumption > 0 else 0, 3),
                    "date_range": {
                        "start": daily_list[0]['date'] if daily_list else None,
                        "end": daily_list[-1]['date'] if daily_list else None
                    }
                },
                "daily_usage": daily_data,
                "daily_list": sorted(daily_list, key=lambda x: x['date']),  # Sorted for graphs
                "temperature": temperature_data,
                "meta": {
                    "source": "mercury_energy_api",
                    "integration": "mercury_co_nz",
                    "endpoint": "http://localhost:8123/local/mercury_daily.json"
                }
            }

            # Write JSON file
            def write_json():
                with open(json_file, 'w') as f:
                    json.dump(json_data, f, indent=2, ensure_ascii=False)

            await asyncio.get_event_loop().run_in_executor(None, write_json)

            _LOGGER.info("✅ Stored daily data in JSON: %d days, %.2f kWh total",
                        num_days, total_consumption)
            _LOGGER.debug("JSON endpoint available at: http://localhost:8123/local/mercury_daily.json")

        except Exception as e:
            _LOGGER.error("❌ Failed to store daily data JSON: %s", e)

    async def _load_extended_hourly_data(self) -> dict[str, Any]:
        """Load extended hourly data from JSON file to expose via sensors (7-day retention)."""
        try:
            www_dir = os.path.join(self.hass.config.config_dir, "www")
            json_file = os.path.join(www_dir, "mercury_hourly.json")

            def load_data():
                if os.path.exists(json_file):
                    try:
                        with open(json_file, 'r') as f:
                            json_data = json.load(f)

                        # Convert hourly_usage dict to list format for sensors
                        hourly_usage = json_data.get('hourly_usage', {})
                        hourly_list = []
                        for datetime_key in sorted(hourly_usage.keys()):
                            hour_data = hourly_usage[datetime_key]
                            hourly_list.append({
                                'datetime': hour_data['timestamp'],  # Full timestamp
                                'date': hour_data['timestamp'],     # Also add 'date' for compatibility
                                'consumption': hour_data['consumption'],
                                'cost': hour_data['cost']
                            })

                        return {
                            'extended_hourly_usage_history': hourly_list,
                            'total_historical_hours': len(hourly_list)
                        }
                    except Exception as e:
                        _LOGGER.warning("Could not load extended hourly data: %s", e)

                return {}

            return await asyncio.get_event_loop().run_in_executor(None, load_data)

        except Exception as e:
            _LOGGER.error("Error loading extended hourly data: %s", e)
            return {}

    async def _load_extended_historical_data(self) -> dict[str, Any]:
        """Load extended historical data from JSON file to expose via sensors."""
        try:
            www_dir = os.path.join(self.hass.config.config_dir, "www")
            json_file = os.path.join(www_dir, "mercury_daily.json")

            def load_data():
                if os.path.exists(json_file):
                    try:
                        with open(json_file, 'r') as f:
                            json_data = json.load(f)

                        # Convert daily_usage dict to list format for sensors
                        daily_usage = json_data.get('daily_usage', {})
                        daily_list = []
                        for date_key in sorted(daily_usage.keys()):
                            day_data = daily_usage[date_key]
                            daily_list.append({
                                'date': day_data['timestamp'],  # Full timestamp
                                'consumption': day_data['consumption'],
                                'cost': day_data['cost'],
                                'free_power': day_data.get('free_power', False)
                            })

                        # Convert temperature dict to list format
                        temperature_data = json_data.get('temperature', {})
                        temp_list = []
                        for date_key in sorted(temperature_data.keys()):
                            temp_data = temperature_data[date_key]
                            temp_list.append({
                                'date': temp_data['timestamp'],  # Full timestamp
                                'temp': temp_data['temperature']
                            })

                        return {
                            'extended_daily_usage_history': daily_list,
                            'extended_temperature_history': temp_list,
                            'total_historical_days': len(daily_list)
                        }
                    except Exception as e:
                        _LOGGER.warning("Could not load extended historical data: %s", e)

                return {}

            return await asyncio.get_event_loop().run_in_executor(None, load_data)

        except Exception as e:
            _LOGGER.error("Error loading extended historical data: %s", e)
            return {}

    async def async_close(self) -> None:
        """Close the API client."""
        await self.api.close()
