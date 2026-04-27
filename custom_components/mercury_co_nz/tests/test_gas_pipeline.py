"""Tests for gas-pipeline plumbing (v1.4.0).

Covers:
- Fuel-aware Store key (electricity must remain unsuffixed for back-compat)
- Fuel-aware metadata (gas suffixes + names)
- _build_monthly_entries logic (one entry per invoice period, monotonic sums,
  cutoff dedup, null/missing handling, hour-aligned UTC anchors)

Mercury's gas API only exposes monthly aggregates, so the gas importer reads
`gas_monthly_usage_history` and produces one StatisticData entry per Mercury
invoice period anchored at invoice_to.
"""

# pylint: disable=protected-access
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from custom_components.mercury_co_nz.const import (
    DOMAIN,
    STATISTICS_GAS_CONSUMPTION_SUFFIX,
    STATISTICS_GAS_COST_SUFFIX,
)
from custom_components.mercury_co_nz.statistics import MercuryStatisticsImporter


def _consume_coro(coro):
    """Close a coroutine without awaiting (avoid ResourceWarning in pure tests)."""
    coro.close()


def _make_gas_importer() -> MercuryStatisticsImporter:
    hass = MagicMock()
    hass.async_create_task = _consume_coro
    hass.config.currency = "NZD"
    return MercuryStatisticsImporter(hass, "user@example.com", fuel_type="gas")


def _make_elec_importer() -> MercuryStatisticsImporter:
    hass = MagicMock()
    hass.async_create_task = _consume_coro
    hass.config.currency = "NZD"
    return MercuryStatisticsImporter(hass, "user@example.com")  # default electricity


def _record(invoice_to: str, consumption: float, cost: float) -> dict:
    """Build a Mercury monthly usage record dict.

    Mirrors the shape of pymercury's ServiceUsage.daily_usage entries
    (which also contains monthly entries when interval='monthly').
    """
    return {
        "date": invoice_to[:10],
        "consumption": consumption,
        "cost": cost,
        "free_power": False,
        "invoice_from": "",
        "invoice_to": invoice_to,
    }


# ----------------------------------------------------------------------------
# Fuel-aware Store key (LOAD-BEARING — guards electricity back-compat)
# ----------------------------------------------------------------------------


def test_store_key_back_compat_for_electricity() -> None:
    """LOAD-BEARING: electricity Store key must NOT include any fuel suffix.

    Existing v1.3.x users have their id_prefix locked under
    f'{DOMAIN}_statistics_{email_hash}'. If this changes on upgrade,
    the lock is lost — every existing electricity series gets an
    'ID changed' ERROR and statistics import is suppressed.
    """
    elec = _make_elec_importer()
    gas = _make_gas_importer()
    assert elec._store.key == f"{DOMAIN}_statistics_{elec._email_hash}"
    assert gas._store.key == f"{DOMAIN}_statistics_gas_{gas._email_hash}"
    assert elec._store.key != gas._store.key


def test_electricity_importer_default_constructor_unchanged() -> None:
    """Single-arg construction (no fuel_type kwarg) still produces electricity.

    The coordinator's existing call site `MercuryStatisticsImporter(hass, email)`
    must continue producing electricity statistics with the existing
    statistic_id suffixes — back-compat for the electricity importer.
    """
    importer = _make_elec_importer()
    energy_meta, _ = importer._build_metadata("acc1")
    assert "energy_consumption" in energy_meta["statistic_id"]
    assert "gas_consumption" not in energy_meta["statistic_id"]


# ----------------------------------------------------------------------------
# Fuel-aware metadata
# ----------------------------------------------------------------------------


def test_gas_importer_uses_gas_suffix() -> None:
    importer = _make_gas_importer()
    energy_meta, cost_meta = importer._build_metadata("acc1")
    assert energy_meta["statistic_id"] == f"{DOMAIN}:acc1_{STATISTICS_GAS_CONSUMPTION_SUFFIX}"
    assert cost_meta["statistic_id"] == f"{DOMAIN}:acc1_{STATISTICS_GAS_COST_SUFFIX}"


def test_gas_importer_name_says_gas() -> None:
    importer = _make_gas_importer()
    energy_meta, cost_meta = importer._build_metadata("acc1")
    assert "gas" in energy_meta["name"].lower()
    assert "gas" in cost_meta["name"].lower()


# ----------------------------------------------------------------------------
# _build_monthly_entries
# ----------------------------------------------------------------------------


def test_monthly_entries_one_per_invoice_period() -> None:
    records = [
        _record("2026-02-01T00:00:00+13:00", 100.0, 25.0),
        _record("2026-03-01T00:00:00+13:00", 80.0, 20.0),
        _record("2026-04-01T00:00:00+13:00", 120.0, 30.0),
    ]
    energy, cost, skipped = MercuryStatisticsImporter._build_monthly_entries(
        records, energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    assert len(energy) == 3
    assert len(cost) == 3
    assert skipped == 0


def test_monthly_entries_sums_are_monotonic() -> None:
    records = [
        _record("2026-02-01T00:00:00+13:00", 100.0, 25.0),
        _record("2026-03-01T00:00:00+13:00", 80.0, 20.0),
        _record("2026-04-01T00:00:00+13:00", 120.0, 30.0),
    ]
    energy, cost, _ = MercuryStatisticsImporter._build_monthly_entries(
        records, energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    assert [e["sum"] for e in energy] == [100.0, 180.0, 300.0]
    assert [c["sum"] for c in cost] == [25.0, 45.0, 75.0]


def test_monthly_entries_skip_records_at_or_before_cutoff() -> None:
    """Cutoff dedup: entries already imported in prior cycles are not re-emitted,
    but their consumption is still added to the running sum so subsequent
    entries continue monotonically from where the recorder left off."""
    records = [
        _record("2026-02-01T00:00:00+13:00", 100.0, 25.0),
        _record("2026-03-01T00:00:00+13:00", 80.0, 20.0),
        _record("2026-04-01T00:00:00+13:00", 120.0, 30.0),
    ]
    # Cutoff just past Feb 1 UTC (Feb 1 NZDT = Jan 31 11:00 UTC) — first record dropped.
    cutoff = datetime(2026, 1, 31, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    energy, _, skipped = MercuryStatisticsImporter._build_monthly_entries(
        records,
        energy_sum_start=100.0,    # carry-over from Feb already in recorder
        cost_sum_start=25.0,
        cutoff_ts=cutoff,
    )
    assert skipped == 0   # null_skip counts only parse/missing failures, not cutoff
    assert len(energy) == 2  # Mar + Apr emitted; Feb skipped via cutoff
    # First emitted entry (March) sum continues from Feb's carry (100) + March (80) = 180
    assert energy[0]["sum"] == 180.0
    assert energy[1]["sum"] == 300.0


def test_monthly_entries_skip_null_consumption() -> None:
    """Future-period estimates may have null consumption — skip and count."""
    records = [
        {"invoice_to": "2026-02-01T00:00:00+13:00", "consumption": None, "cost": None},
        _record("2026-03-01T00:00:00+13:00", 80.0, 20.0),
    ]
    energy, _, skipped = MercuryStatisticsImporter._build_monthly_entries(
        records, energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    assert skipped == 1
    assert len(energy) == 1


def test_monthly_entries_skip_missing_invoice_to_and_date() -> None:
    """Records with neither invoice_to nor date can't be anchored — skip."""
    records = [
        {"consumption": 100.0, "cost": 25.0},  # no anchor at all
        _record("2026-03-01T00:00:00+13:00", 80.0, 20.0),
    ]
    energy, _, skipped = MercuryStatisticsImporter._build_monthly_entries(
        records, energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    assert skipped == 1
    assert len(energy) == 1


def test_monthly_entries_anchor_is_hour_aligned_utc() -> None:
    """All emitted entries must have hour-aligned UTC start (recorder requirement)."""
    records = [_record("2026-04-01T13:30:45+13:00", 100.0, 25.0)]
    energy, _, _ = MercuryStatisticsImporter._build_monthly_entries(
        records, energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    anchor = energy[0]["start"]
    assert anchor.tzinfo is not None
    assert anchor.utcoffset().total_seconds() == 0  # UTC
    assert anchor.minute == 0
    assert anchor.second == 0
    assert anchor.microsecond == 0


def test_monthly_entries_falls_back_to_date_when_invoice_to_missing() -> None:
    """Records with only `date` (no invoice_to) still produce entries."""
    records = [
        {"date": "2026-03-31", "consumption": 80.0, "cost": 20.0},
    ]
    energy, _, skipped = MercuryStatisticsImporter._build_monthly_entries(
        records, energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    assert skipped == 0
    assert len(energy) == 1


def test_monthly_entries_handles_unsorted_input() -> None:
    """Records may arrive out of order from Mercury — sums must still be monotonic
    after internal sort."""
    records = [
        _record("2026-04-01T00:00:00+13:00", 120.0, 30.0),  # latest first
        _record("2026-02-01T00:00:00+13:00", 100.0, 25.0),
        _record("2026-03-01T00:00:00+13:00", 80.0, 20.0),
    ]
    energy, _, _ = MercuryStatisticsImporter._build_monthly_entries(
        records, energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    sums = [e["sum"] for e in energy]
    assert sums == sorted(sums)
    assert sums == [100.0, 180.0, 300.0]


def test_monthly_entries_empty_input_returns_empty() -> None:
    energy, cost, skipped = MercuryStatisticsImporter._build_monthly_entries(
        [], energy_sum_start=0.0, cost_sum_start=0.0, cutoff_ts=0.0
    )
    assert energy == []
    assert cost == []
    assert skipped == 0


# ----------------------------------------------------------------------------
# v2.0.0 — multi-ICP × gas composition
# ----------------------------------------------------------------------------


def test_gas_importer_with_secondary_icp_has_compound_store_key() -> None:
    """Gas + non-primary ICP must have BOTH fuel and icp suffixes in the
    Store key so the lock doesn't collide with primary gas or other gas ICPs."""
    hass = MagicMock()
    hass.async_create_task = _consume_coro
    hass.config.currency = "NZD"
    gas_secondary = MercuryStatisticsImporter(
        hass,
        "user@example.com",
        fuel_type="gas",
        service_id="ICP_GAS_002",
        is_primary=False,
    )
    assert "_gas_" in gas_secondary._store.key
    assert "icp_gas_002" in gas_secondary._store.key.lower()


def test_gas_primary_icp_back_compat_store_key_unchanged() -> None:
    """LOAD-BEARING: gas primary ICP Store key must match v1.4.1 byte-for-byte —
    the existing fuel_type='gas' construction with default service_id/is_primary
    produces f"{DOMAIN}_statistics_gas_{email_hash}" as before, no icp suffix.
    """
    from custom_components.mercury_co_nz.const import DOMAIN

    hass = MagicMock()
    hass.async_create_task = _consume_coro
    hass.config.currency = "NZD"
    # Default is_primary=True, service_id=None
    gas_primary = MercuryStatisticsImporter(
        hass, "user@example.com", fuel_type="gas"
    )
    assert gas_primary._store.key == f"{DOMAIN}_statistics_gas_{gas_primary._email_hash}"
