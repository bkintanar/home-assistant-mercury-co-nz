"""Long-term statistics importer for Mercury Energy NZ (Energy Dashboard)."""

# pylint: disable=protected-access
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
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
    STATISTICS_GAS_CONSUMPTION_SUFFIX,
    STATISTICS_GAS_COST_SUFFIX,
    STATISTICS_REIMPORT_DAYS,
)

_LOGGER = logging.getLogger(__name__)

_NOTIFICATION_ID = "mercury_co_nz_statistics_failed"
_STORE_VERSION = 1


def _sanitize_for_key(service_id: str | None) -> str:
    """Sanitize a service_id for use in Store keys, statistic_ids, entity_ids.

    Replaces dashes/dots with underscores and lowercases. Used both here
    and in coordinator.py for consistent ICP token generation.
    """
    if not service_id:
        return "primary"
    return str(service_id).replace("-", "_").replace(".", "_").lower()


class MercuryStatisticsImporter:
    """Push Mercury kWh + NZD costs into HA's long-term statistics table.

    Mercury's API exposes per-hour and per-day data with a ~2-day lag. Live
    `total_increasing` sensors would freeze for 48h producing zero-kWh bins
    followed by a spike. This class mirrors the Opower core integration's
    pattern: push external statistics directly to the recorder, backfilling
    up to 180 days on first run, re-importing the trailing few days each
    run to absorb bill corrections.

    For each NZ-local day, real per-hour values from `extended_hourly_usage_history`
    are emitted verbatim. Days not yet covered by the hourly cache fall back to
    the daily total split evenly across 23/24/25 hours (DST-aware).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        email: str,
        fuel_type: Literal["electricity", "gas"] = "electricity",
        service_id: str | None = None,
        is_primary: bool = True,
    ) -> None:
        """Initialise; schedule async load of any persisted id_prefix.

        Default args (fuel_type='electricity', service_id=None, is_primary=True)
        produce byte-identical Store key, statistic_ids, and names to v1.4.1 —
        single-arg construction continues to work for back-compat.

        For multi-ICP (v2.0.0): non-primary ICPs include an icp_token suffix
        in the Store key AND in statistic_ids. Primary ICP keeps the legacy
        formula so existing users' id_prefix lock + Energy Dashboard history
        survive the upgrade.
        """
        self._hass = hass
        self._email = email
        self._fuel_type = fuel_type
        self._service_id = service_id
        self._is_primary = is_primary
        self._email_hash = hashlib.md5(email.encode()).hexdigest()[:8]
        fuel_suffix = "" if fuel_type == "electricity" else f"_{fuel_type}"
        # LOAD-BEARING: only non-primary ICPs add the icp_suffix. Primary's
        # Store key MUST match v1.4.1 exactly: f"{DOMAIN}_statistics_{email_hash}"
        # for elec, f"{DOMAIN}_statistics_gas_{email_hash}" for gas.
        icp_suffix = "" if is_primary else f"_{_sanitize_for_key(service_id)}"
        self._store: Store = Store(
            hass,
            version=_STORE_VERSION,
            key=f"{DOMAIN}_statistics{fuel_suffix}{icp_suffix}_{self._email_hash}",
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
        if self._fuel_type == "gas":
            consumption_suffix = STATISTICS_GAS_CONSUMPTION_SUFFIX
            cost_suffix = STATISTICS_GAS_COST_SUFFIX
            fuel_word = "gas "
        else:
            consumption_suffix = STATISTICS_ENERGY_SUFFIX
            cost_suffix = STATISTICS_COST_SUFFIX
            fuel_word = ""

        # LOAD-BEARING: only non-primary ICPs add the icp_token. Primary's
        # statistic_id MUST match v1.4.1 exactly: e.g. f"{DOMAIN}:{id_prefix}_energy_consumption"
        icp_token = "" if self._is_primary else f"_{_sanitize_for_key(self._service_id)}"
        consumption_name = f"Mercury {id_prefix}{icp_token} {fuel_word}consumption".replace("  ", " ").strip()
        cost_name = f"Mercury {id_prefix}{icp_token} {fuel_word}cost".replace("  ", " ").strip()
        energy_statistic_id = f"{DOMAIN}:{id_prefix}{icp_token}_{consumption_suffix}"
        cost_statistic_id = f"{DOMAIN}:{id_prefix}{icp_token}_{cost_suffix}"

        energy_meta = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=consumption_name,
            source=DOMAIN,
            statistic_id=energy_statistic_id,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        cost_meta = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=cost_name,
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
    def _parse_invoice_end_utc(raw: str) -> datetime | None:
        """Parse Mercury's invoice_to / month-start string into hour-aligned UTC.

        Accepts:
        - Full ISO with offset: '2026-04-30T10:00:00+13:00'
        - Naive datetime: '2026-04-30T00:00:00' (assumed NZ-local)
        - Date-only: '2026-04-30' (assumed NZ-local midnight)

        Returns None on parse failure so the caller can increment its skip counter.
        """
        if not isinstance(raw, str) or not raw.strip():
            return None
        s = raw.strip()
        nz = ZoneInfo(NZ_TIMEZONE)
        try:
            if "T" not in s:
                # Date-only — treat as NZ-local midnight at the start of that day.
                parsed = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=nz)
            else:
                parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=nz)
        except ValueError:
            return None
        utc = parsed.astimezone(timezone.utc)
        return utc.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _build_monthly_entries(
        monthly_records: list[dict[str, Any]],
        energy_sum_start: float,
        cost_sum_start: float,
        cutoff_ts: float,
    ) -> tuple[list[StatisticData], list[StatisticData], int]:
        """Build one StatisticData per Mercury invoice period (gas only).

        Mercury's gas API only returns monthly aggregates. Each input record
        represents an invoice period with `consumption` (kWh), `cost` (NZD),
        `invoice_from`, `invoice_to`, and `date`. We anchor the entry at
        invoice_to (end of period) — consumption "completed" by then —
        hour-aligned to UTC. Sums accumulate chronologically so the series
        is strictly monotonic.

        Mirrors the (signature, return-tuple, skip-counter) contract of
        `_build_hourly_entries` so async_update can branch on fuel_type
        without changing the surrounding flow.
        """
        skipped = 0
        # invoice_to_utc -> (kwh, cost)
        buckets: dict[datetime, tuple[float, float]] = {}

        for record in monthly_records or []:
            invoice_to_raw = record.get("invoice_to") or record.get("date")
            if not isinstance(invoice_to_raw, str):
                skipped += 1
                continue
            anchor = MercuryStatisticsImporter._parse_invoice_end_utc(invoice_to_raw)
            if anchor is None:
                skipped += 1
                continue
            consumption = record.get("consumption")
            cost = record.get("cost")
            if consumption is None or cost is None:
                skipped += 1
                continue
            buckets[anchor] = (float(consumption), float(cost))

        # Filter out records already imported (anchor at or before cutoff).
        # `energy_sum_start` represents the recorder's cumulative sum at the
        # last imported entry, so new emissions accumulate from there — pre-cutoff
        # buckets must NOT contribute or we double-count.
        sorted_anchors = [
            a for a in sorted(buckets.keys()) if a.timestamp() > cutoff_ts
        ]
        energy_running = float(energy_sum_start or 0.0)
        cost_running = float(cost_sum_start or 0.0)
        energy_stats: list[StatisticData] = []
        cost_stats: list[StatisticData] = []

        for anchor in sorted_anchors:
            kwh, cost = buckets[anchor]
            energy_running += kwh
            cost_running += cost
            energy_stats.append(
                StatisticData(start=anchor, state=kwh, sum=energy_running)
            )
            cost_stats.append(
                StatisticData(start=anchor, state=cost, sum=cost_running)
            )

        return energy_stats, cost_stats, skipped

    @staticmethod
    def _parse_hour_start_utc(record: dict[str, Any]) -> datetime | None:
        """Parse the start-of-hour UTC datetime for an hourly record.

        Hourly rows arrive with 'date'/'datetime' as a full ISO timestamp
        (NZ-local with offset, e.g. 2026-04-25T14:00:00+12:00). Both keys
        map to the same value for extended_hourly_usage_history rows
        (coordinator.py:454-456); raw hourly_usage_history rows only have
        'date'. Truncate to the hour boundary in UTC to align with the
        daily-split slot grid so async_add_external_statistics upserts
        cleanly when a slot was previously written by the daily path.
        """
        raw = record.get("datetime") or record.get("date")
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        utc = parsed.astimezone(timezone.utc)
        return utc.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _build_hourly_entries(
        daily_records: list[dict[str, Any]],
        hourly_records: list[dict[str, Any]],
        energy_sum_start: float,
        cost_sum_start: float,
        cutoff_ts: float,
    ) -> tuple[list[StatisticData], list[StatisticData], int]:
        """Build hourly StatisticData entries, preferring real per-hour data.

        Hourly records are consumed verbatim — one input row produces exactly
        one output entry. Daily records are split across the actual NZ-local
        hour count (23/24/25, DST-aware) ONLY for NZ-local days not already
        covered by the hourly source. Sums are accumulated chronologically
        across the merged set so the series is strictly monotonic regardless
        of which source filled each bucket.
        """
        nz = ZoneInfo(NZ_TIMEZONE)
        null_skip_count = 0
        # hour_start_utc -> (kwh, cost)
        buckets: dict[datetime, tuple[float, float]] = {}

        # 1. Hourly records first — real data wins.
        for record in hourly_records or []:
            hour_start = MercuryStatisticsImporter._parse_hour_start_utc(record)
            if hour_start is None:
                null_skip_count += 1
                continue
            consumption = record.get("consumption")
            cost = record.get("cost")
            # Note: extended_hourly_usage_history rows arrive with `cost`
            # already normalised to 0.0 by the coordinator JSON cache when
            # Mercury omits the field (coordinator.py:237). The None check
            # here only fires for live `hourly_usage_history` rows passed
            # directly from the API. Zero-cost hours ARE emitted as a real
            # zero — verify via mercury_hourly.json after first deploy.
            if consumption is None or cost is None:
                null_skip_count += 1
                continue
            buckets[hour_start] = (float(consumption), float(cost))

        # 2. NZ-local dates already covered by hourly — skip these days in the
        #    daily-split pass to avoid double-filling.
        hourly_covered_nz_dates: set[tuple[int, int, int]] = set()
        for hour_start in buckets:
            nz_local = hour_start.astimezone(nz)
            hourly_covered_nz_dates.add(
                (nz_local.year, nz_local.month, nz_local.day)
            )

        # 3. Daily records — fill uncovered NZ-local days via the 23/24/25 split.
        for record in daily_records or []:
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

            nz_date_key = (parsed_dt.year, parsed_dt.month, parsed_dt.day)
            if nz_date_key in hourly_covered_nz_dates:
                continue

            nz_midnight = datetime(
                parsed_dt.year, parsed_dt.month, parsed_dt.day, tzinfo=nz
            )
            next_nz_midnight = nz_midnight + timedelta(days=1)
            current_utc = nz_midnight.astimezone(timezone.utc)
            end_utc = next_nz_midnight.astimezone(timezone.utc)

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

            slot = current_utc
            while slot < end_utc:
                buckets.setdefault(slot, (hourly_kwh, hourly_cost))
                slot += timedelta(hours=1)

        # 4. Emit chronologically with cumulative sums; skip slots before cutoff.
        energy_stats: list[StatisticData] = []
        cost_stats: list[StatisticData] = []
        for slot in sorted(buckets.keys()):
            if slot.timestamp() < cutoff_ts:
                continue
            kwh, cost_value = buckets[slot]
            energy_sum_start += kwh
            cost_sum_start += cost_value
            energy_stats.append(
                StatisticData(start=slot, state=kwh, sum=energy_sum_start)
            )
            cost_stats.append(
                StatisticData(start=slot, state=cost_value, sum=cost_sum_start)
            )

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

        # 3. Pull records based on fuel_type. Electricity uses daily+hourly
        #    (with daily-split fallback); gas uses monthly only (Mercury's API
        #    doesn't expose sub-monthly gas data — confirmed via maintainer testing).
        if self._fuel_type == "gas":
            monthly_records = coordinator_data.get("gas_monthly_usage_history") or []
            daily_records: list[dict[str, Any]] = []
            hourly_records: list[dict[str, Any]] = []
            if not monthly_records:
                _LOGGER.debug("Mercury statistics (gas): no monthly records available; skipping")
                return
        else:
            monthly_records = []
            daily_records = (
                coordinator_data.get("extended_daily_usage_history")
                or coordinator_data.get("daily_usage_history")
                or []
            )
            hourly_records = (
                coordinator_data.get("extended_hourly_usage_history")
                or coordinator_data.get("hourly_usage_history")
                or []
            )
            if not daily_records and not hourly_records:
                _LOGGER.debug("Mercury statistics: no usage records available; skipping")
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

            if self._fuel_type == "gas":
                energy_stats, cost_stats, null_skip_count = self._build_monthly_entries(
                    monthly_records,
                    last_sum_energy or 0.0,
                    last_sum_cost or 0.0,
                    cutoff_ts,
                )
            else:
                energy_stats, cost_stats, null_skip_count = self._build_hourly_entries(
                    daily_records,
                    hourly_records,
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
