"""Data update coordinator for Mercury Energy NZ."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
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

            # 🎯 Store daily data in JSON file for dynamic graphs
            await self._store_daily_data_json(combined_data)

            # Load extended historical data to expose via sensors
            extended_data = await self._load_extended_historical_data()
            if extended_data:
                # Update the combined data with extended history (more than 14 days)
                combined_data.update(extended_data)
                _LOGGER.info("Enhanced data with %d days of usage history and %d days of temperature history",
                           len(extended_data.get('extended_daily_usage_history', [])),
                           len(extended_data.get('extended_temperature_history', [])))

            return combined_data
        except Exception as exception:
            _LOGGER.error("Mercury coordinator: Error communicating with API: %s", exception)
            raise UpdateFailed(f"Error communicating with API: {exception}") from exception

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
