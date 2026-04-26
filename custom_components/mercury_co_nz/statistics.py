"""Long-term statistics importer for Mercury Energy NZ (Energy Dashboard)."""

# pylint: disable=protected-access
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components import persistent_notification
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .const import (
    DOMAIN,
    NZ_TIMEZONE,
    STATISTICS_COST_SUFFIX,
    STATISTICS_ENERGY_SUFFIX,
    STATISTICS_FAILURE_BACKOFF_THRESHOLD,
    STATISTICS_FAILURE_NOTIFICATION_THRESHOLD,
    STATISTICS_REIMPORT_DAYS,
)

_LOGGER = logging.getLogger(__name__)

_NOTIFICATION_ID = "mercury_co_nz_statistics_failed"
_STORE_VERSION = 1


class MercuryStatisticsImporter:
    """Push Mercury daily kWh + NZD costs into HA's long-term statistics table.

    Mercury's API delivers daily totals with a ~2-day delay. Live `total_increasing`
    sensors would freeze for 48h producing zero-kWh bins followed by a spike — wrong
    Energy Dashboard graphs. This class mirrors the Opower core integration's pattern:
    push external statistics directly to the recorder, backfilling up to 180 days on
    first run, re-importing the trailing few days each run to absorb bill corrections.
    """

    def __init__(self, hass: HomeAssistant, email: str) -> None:
        """Initialise; schedule async load of any persisted id_prefix."""
        self._hass = hass
        self._email = email
        self._email_hash = hashlib.md5(email.encode()).hexdigest()[:8]
        self._store: Store = Store(
            hass,
            version=_STORE_VERSION,
            key=f"{DOMAIN}_statistics_{self._email_hash}",
        )
        self._id_prefix: str | None = None
        self._consecutive_failures: int = 0
        self._currency_warning_emitted: bool = False
        self._notification_sent: bool = False

        # Load persisted id_prefix in the background so the lock survives restart.
        self._hass.async_create_task(self._async_load_persisted_prefix())

    async def _async_load_persisted_prefix(self) -> None:
        """Rehydrate _id_prefix from disk so the lock holds across HA restarts."""
        try:
            data = await self._store.async_load()
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Mercury statistics: failed to load persisted id_prefix (%s); "
                "lock will re-establish on next successful build",
                exc,
            )
            return
        if isinstance(data, dict) and isinstance(data.get("id_prefix"), str):
            self._id_prefix = data["id_prefix"]
            _LOGGER.debug(
                "Mercury statistics: rehydrated id_prefix=%s from store",
                self._id_prefix,
            )

    @staticmethod
    def _build_id_prefix(account_id: str | None, email_hash: str) -> str:
        """Sanitize account_id for VALID_STATISTIC_ID; fall back to email hash."""
        if account_id:
            return str(account_id).replace("-", "_").replace(".", "_").lower()
        return f"acct_{email_hash}"

    def _build_metadata(
        self, id_prefix: str
    ) -> tuple[StatisticMetaData, StatisticMetaData]:
        """Build the energy + cost StatisticMetaData pair.

        `mean_type` and `unit_class` are both REQUIRED keys in the TypedDict
        (verified against HA 2025.11+ recorder/models/statistics.py). `unit_class=None`
        for cost skips unit conversion so any string (including "NZD") is accepted.
        """
        energy_statistic_id = f"{DOMAIN}:{id_prefix}_{STATISTICS_ENERGY_SUFFIX}"
        cost_statistic_id = f"{DOMAIN}:{id_prefix}_{STATISTICS_COST_SUFFIX}"

        energy_meta = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Mercury {id_prefix} consumption",
            source=DOMAIN,
            statistic_id=energy_statistic_id,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        cost_meta = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Mercury {id_prefix} cost",
            source=DOMAIN,
            statistic_id=cost_statistic_id,
            unit_class=None,
            unit_of_measurement="NZD",
        )
        return energy_meta, cost_meta

    async def _async_get_last_imported(
        self, statistic_id: str
    ) -> tuple[float, float | None]:
        """Return (last_sum, last_start_ts) for an existing statistic.

        Defends against `get_last_statistics` returning either {} (no key) or
        {statistic_id: []} (key present, empty list) on no-data — both forms occur
        across HA versions.
        """
        last_stat = await get_instance(self._hass).async_add_executor_job(
            get_last_statistics, self._hass, 1, statistic_id, True, {"sum"}
        )
        entries = last_stat.get(statistic_id, []) if last_stat else []
        if not entries:
            return 0.0, None
        entry = entries[0]
        last_sum = entry.get("sum")
        last_start = entry.get("start")
        return float(last_sum if last_sum is not None else 0.0), last_start

    @staticmethod
    def _build_hourly_entries(
        records: list[dict[str, Any]],
        energy_sum_start: float,
        cost_sum_start: float,
        cutoff_ts: float,
    ) -> tuple[list[StatisticData], list[StatisticData], int]:
        """Split each daily record across 23/24/25 hourly StatisticData entries.

        Mercury delivers daily totals; the Energy Dashboard needs hourly statistics.
        We split each daily kWh/cost evenly across the actual local-day hour count
        (23 on NZDT-start, 25 on NZDT-end, 24 otherwise) so the dashboard hourly
        view shows a smooth profile rather than a midnight spike + 23 zero hours.
        """
        nz = ZoneInfo(NZ_TIMEZONE)
        energy_stats: list[StatisticData] = []
        cost_stats: list[StatisticData] = []
        null_skip_count = 0

        for record in records:
            consumption = record.get("consumption")
            cost = record.get("cost")
            if consumption is None or cost is None:
                null_skip_count += 1
                continue

            raw = record.get("date")
            if not isinstance(raw, str):
                null_skip_count += 1
                continue
            try:
                # `extended_daily_usage_history` populates 'date' from the upstream
                # 'timestamp' field — full ISO `YYYY-MM-DDTHH:MM:SS`. Discard the
                # time component; every Mercury day starts at NZ-local 00:00:00.
                parsed_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                null_skip_count += 1
                continue

            nz_midnight = datetime(
                parsed_dt.year, parsed_dt.month, parsed_dt.day, tzinfo=nz
            )
            next_nz_midnight = nz_midnight + timedelta(days=1)
            current_utc = nz_midnight.astimezone(timezone.utc)
            end_utc = next_nz_midnight.astimezone(timezone.utc)

            # First pass: count actual hours in this local day (23/24/25).
            hours_in_day = 0
            probe = current_utc
            while probe < end_utc:
                hours_in_day += 1
                probe += timedelta(hours=1)
            if hours_in_day == 0:
                null_skip_count += 1
                continue

            hourly_kwh = float(consumption) / hours_in_day
            hourly_cost = float(cost) / hours_in_day

            # Second pass: emit entries, skipping anything strictly before cutoff.
            while current_utc < end_utc:
                if current_utc.timestamp() < cutoff_ts:
                    current_utc += timedelta(hours=1)
                    continue
                energy_sum_start += hourly_kwh
                cost_sum_start += hourly_cost
                energy_stats.append(
                    StatisticData(
                        start=current_utc,
                        state=hourly_kwh,
                        sum=energy_sum_start,
                    )
                )
                cost_stats.append(
                    StatisticData(
                        start=current_utc,
                        state=hourly_cost,
                        sum=cost_sum_start,
                    )
                )
                current_utc += timedelta(hours=1)

        return energy_stats, cost_stats, null_skip_count

    async def async_update(self, coordinator_data: dict[str, Any]) -> None:
        """Push Mercury statistics to the recorder. Called once per coordinator update.

        Logic errors propagate to the caller (the coordinator hook) which logs at
        ERROR with `exc_info=True`. Only recorder-not-ready scenarios are caught
        here, with a backoff counter to prevent infinite log spam.
        """
        # 1. Resolve and validate the id_prefix.
        account_id = coordinator_data.get("bill_account_id")
        candidate = self._build_id_prefix(account_id, self._email_hash)

        if self._id_prefix is not None and candidate != self._id_prefix:
            _LOGGER.error(
                "Mercury statistics ID changed from %r to %r. Old history is "
                "orphaned. Remove 'mercury_co_nz:%s_*' from Settings → Dashboards "
                "→ Energy and re-add 'mercury_co_nz:%s_*'.",
                self._id_prefix,
                candidate,
                self._id_prefix,
                candidate,
            )
            return

        if self._id_prefix is None:
            self._id_prefix = candidate
            try:
                await self._store.async_save(
                    {
                        "id_prefix": candidate,
                        "first_seen": dt_util.utcnow().isoformat(),
                    }
                )
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.warning(
                    "Mercury statistics: failed to persist id_prefix (%s); "
                    "lock holds in-session only until next successful save",
                    exc,
                )

        # 2. One-time currency advisory.
        if not self._currency_warning_emitted and self._hass.config.currency != "NZD":
            _LOGGER.info(
                "Mercury statistics: HA currency is %s but Mercury costs are NZD. "
                "Energy Dashboard cost labels may be wrong. Set 'currency: NZD' in "
                "your configuration.yaml under 'homeassistant:' and restart.",
                self._hass.config.currency,
            )
            self._currency_warning_emitted = True

        # 3. Pull daily records (extended history preferred for backfill).
        records = coordinator_data.get(
            "extended_daily_usage_history"
        ) or coordinator_data.get("daily_usage_history")
        if not records:
            _LOGGER.debug("Mercury statistics: no daily records available; skipping")
            return

        # 4. Recorder readiness gate (only failure type swallowed locally).
        try:
            get_instance(self._hass)
        except (KeyError, RuntimeError) as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures == STATISTICS_FAILURE_NOTIFICATION_THRESHOLD:
                persistent_notification.async_create(
                    self._hass,
                    message=(
                        "Mercury energy statistics import has failed for ~15 "
                        "minutes. Check Home Assistant logs for details."
                    ),
                    title="Mercury Energy NZ",
                    notification_id=_NOTIFICATION_ID,
                )
                self._notification_sent = True
            if self._consecutive_failures == STATISTICS_FAILURE_BACKOFF_THRESHOLD:
                _LOGGER.error(
                    "Mercury statistics: recorder unavailable after %d attempts (~1h); "
                    "stopping retries until HA restart. Last error: %s",
                    self._consecutive_failures,
                    exc,
                )
            return

        # 5+. Logic errors below propagate to coordinator hook.
        try:
            energy_meta, cost_meta = self._build_metadata(self._id_prefix)

            last_sum_energy, last_ts_energy = await self._async_get_last_imported(
                energy_meta["statistic_id"]
            )
            last_sum_cost, _last_ts_cost = await self._async_get_last_imported(
                cost_meta["statistic_id"]
            )

            cutoff_ts: float = (
                last_ts_energy or 0.0
            ) - STATISTICS_REIMPORT_DAYS * 86400

            energy_stats, cost_stats, null_skip_count = self._build_hourly_entries(
                records,
                last_sum_energy or 0.0,
                last_sum_cost or 0.0,
                cutoff_ts,
            )

            if not energy_stats and not cost_stats:
                _LOGGER.debug(
                    "Mercury statistics: nothing to import "
                    "(cutoff_ts=%s, null_skipped=%d)",
                    cutoff_ts,
                    null_skip_count,
                )
            else:
                async_add_external_statistics(self._hass, energy_meta, energy_stats)
                async_add_external_statistics(self._hass, cost_meta, cost_stats)

                summary = (
                    "Mercury statistics: imported %d hourly entries "
                    "(energy + cost), skipped %d null records"
                )
                if null_skip_count > 7:
                    _LOGGER.warning(summary, len(energy_stats), null_skip_count)
                else:
                    _LOGGER.info(summary, len(energy_stats), null_skip_count)
        finally:
            # Always reset the failure counter and dismiss any stale notification on
            # a successful update path. Dismissal is unconditional — safe no-op if
            # no notification exists, robust across config-entry reload.
            self._consecutive_failures = 0
            persistent_notification.async_dismiss(self._hass, _NOTIFICATION_ID)
            self._notification_sent = False
