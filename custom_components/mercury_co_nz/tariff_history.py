"""Retain source hours and import explicitly configured day/night statistics."""

import asyncio
import hashlib
from datetime import datetime
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.core import CoreState
from homeassistant.helpers.storage import Store

from .tariff import Schedule, UTC, build_breakdown, fingerprint, normalize_hours

LOGGER = logging.getLogger(__name__)


class TariffHistory:
    def __init__(self, hass, entry_id, service_id):
        self.hass = hass
        self.service_id = service_id
        # Entry and meter scoped; contains only readings, no credentials.
        self.store = Store(hass, 1, f"mercury_co_nz_tariff_{entry_id}_{service_id}")
        self.saved = None
        self.lock = asyncio.Lock()
        self.submitted = None

    async def async_update(self, records, options):
        async with self.lock:
            if self.saved is None:
                self.saved = await self.store.async_load() or {"hours": {}}
            hours = self.saved["hours"]
            incoming = normalize_hours(records)
            # Older chart caches omit quality flags; do not erase a previously
            # retained provider flag merely by replaying one of those copies.
            for epoch, row in incoming.items():
                for key in ("is_estimated", "read_type"):
                    if row[key] is None and epoch in hours:
                        row[key] = hours[epoch].get(key)
            changed = any(hours.get(k) != v for k, v in incoming.items())
            if changed:
                hours.update(incoming)
                await self.store.async_save(self.saved)
            result = {
                "tariff_usage_details": {"classification": "user_configured_schedule"},
                "usage_latest_reading": None,
                "usage_read_type": None,
            }
            if hours:
                last = max(hours, key=int)
                result["usage_latest_reading"] = datetime.fromtimestamp(int(last), UTC)
                result["usage_read_type"] = hours[last].get("read_type") or (
                    "estimated"
                    if hours[last].get("is_estimated") is True
                    else "actual"
                    if hours[last].get("is_estimated") is False
                    else None
                )
            try:
                schedule = Schedule.from_options(options)
            except (KeyError, ValueError, TypeError):
                LOGGER.error(
                    "Invalid day/night schedule for service %s; leaving split unknown",
                    self.service_id,
                )
                return result
            if schedule is None:
                return result
            token = fingerprint(hours, schedule)
            series = await self.hass.async_add_executor_job(
                build_breakdown, dict(hours), schedule
            )
            details = result["tariff_usage_details"]
            details.update({"schedule": options, "hour_count": len(series["day"])})
            # Never wait for recorder startup from first coordinator refresh.
            # Next regular refresh imports once HA is running. On restart,
            # resubmit idempotently so a lost recorder queue cannot cause gaps.
            if token != self.submitted and self.hass.state is CoreState.running:
                ids = {}
                for period, rows in series.items():
                    if not rows:
                        continue
                    identity = hashlib.sha256(self.store.key.encode()).hexdigest()[:16]
                    stat_id = f"mercury_co_nz:tariff_{identity}_{schedule.key}_{period}"
                    meta = {
                        "statistic_id": stat_id,
                        "source": "mercury_co_nz",
                        "name": f"Mercury {self.service_id} — {period} usage (calculated, {schedule.key})",
                        "unit_of_measurement": "kWh",
                        "mean_type": StatisticMeanType.NONE,
                        "unit_class": "energy",
                        "has_sum": True,
                    }
                    get_instance(self.hass)  # Fail visibly if recorder isn't available.
                    async_add_external_statistics(self.hass, meta, rows)
                    ids[period] = stat_id
                self.submitted = token
                self.saved["statistic_ids"] = ids
                await self.store.async_save(self.saved)
            details["statistic_ids"] = {
                k: v
                for k, v in self.saved.get("statistic_ids", {}).items()
                if f"_{schedule.key}_" in v
            }
            return result
