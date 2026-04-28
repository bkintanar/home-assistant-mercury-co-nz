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
from custom_components.mercury_co_nz.mercury_api import _collapse_gas_pairs
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


# ----------------------------------------------------------------------------
# v1.5.2 — _collapse_gas_pairs (Mercury parallel estimate/actual pair handling)
# ----------------------------------------------------------------------------


def _pair_record(
    invoice_from: str,
    invoice_to: str,
    consumption: float,
    cost: float,
    is_estimated: bool,
) -> dict:
    """Build a pymercury 1.1.2-shaped record (one half of an estimate/actual pair)."""
    return {
        "date": invoice_to,
        "consumption": consumption,
        "cost": cost,
        "free_power": False,
        "invoice_from": invoice_from,
        "invoice_to": invoice_to,
        "is_estimated": is_estimated,
        "read_type": "estimate" if is_estimated else "actual",
    }


def test_collapse_picks_actual_when_estimate_pair_is_zero() -> None:
    """For 27 March (the user's reported anchor), Mercury returns
    estimate=0/actual=460 — the collapse must pick the actual entry."""
    pairs = [
        _pair_record("2026-02-27", "2026-03-27", 0, 0, is_estimated=True),
        _pair_record("2026-02-27", "2026-03-27", 460, 156.28, is_estimated=False),
    ]
    collapsed = _collapse_gas_pairs(pairs)
    assert len(collapsed) == 1
    assert collapsed[0]["consumption"] == 460
    assert collapsed[0]["is_estimated"] is False


def test_collapse_picks_estimate_when_actual_pair_is_zero() -> None:
    """For 26 February in the user's data, Mercury returns
    estimate=397/actual=0 — the v1.5.1 bucketize-overwrite bug dropped the
    real value to zero. Collapse must keep the non-zero estimate."""
    pairs = [
        _pair_record("2026-01-31", "2026-02-26", 397, 139.20, is_estimated=True),
        _pair_record("2026-01-31", "2026-02-26", 0, 0, is_estimated=False),
    ]
    collapsed = _collapse_gas_pairs(pairs)
    assert len(collapsed) == 1
    assert collapsed[0]["consumption"] == 397
    assert collapsed[0]["is_estimated"] is True


def test_collapse_full_year_real_shape_sums_to_total_usage() -> None:
    """Captured-shape regression: 10 billing periods × 2 groups → 10 collapsed
    entries summing to 4842 kWh (the user's real annual gas consumption)."""
    pairs = [
        # period: (invoice_from, invoice_to, est, act, real_value, tag)
        _pair_record("2025-06-14", "2025-07-01",   0,   0.00, True),
        _pair_record("2025-06-14", "2025-07-01", 324,  91.08, False),
        _pair_record("2025-07-02", "2025-07-30", 517, 145.86, True),
        _pair_record("2025-07-02", "2025-07-30",   0,   0.00, False),
        _pair_record("2025-07-31", "2025-08-29",   0,   0.00, True),
        _pair_record("2025-07-31", "2025-08-29", 539, 151.61, False),
        _pair_record("2025-08-30", "2025-09-30", 571, 183.68, True),
        _pair_record("2025-08-30", "2025-09-30",   0,   0.00, False),
        _pair_record("2025-10-01", "2025-10-30",   0,   0.00, True),
        _pair_record("2025-10-01", "2025-10-30", 635, 193.68, False),
        _pair_record("2025-10-31", "2025-11-27",   0,   0.00, True),
        _pair_record("2025-10-31", "2025-11-27", 463, 154.67, False),
        _pair_record("2025-11-28", "2025-12-27", 493, 165.11, True),
        _pair_record("2025-11-28", "2025-12-27",   0,   0.00, False),
        _pair_record("2025-12-28", "2026-01-30",   0,   0.00, True),
        _pair_record("2025-12-28", "2026-01-30", 443, 163.84, False),
        _pair_record("2026-01-31", "2026-02-26", 397, 139.20, True),
        _pair_record("2026-01-31", "2026-02-26",   0,   0.00, False),
        _pair_record("2026-02-27", "2026-03-27",   0,   0.00, True),
        _pair_record("2026-02-27", "2026-03-27", 460, 156.28, False),
    ]
    collapsed = _collapse_gas_pairs(pairs)
    assert len(collapsed) == 10
    assert sum(c["consumption"] for c in collapsed) == 4842
    # Order is chronological by invoice_to.
    assert [c["invoice_to"] for c in collapsed] == sorted(
        c["invoice_to"] for c in collapsed
    )


def test_collapse_tie_break_prefers_actual() -> None:
    """If Mercury ever returns equal non-zero values for both groups (a
    reissued read), pick the actual."""
    pairs = [
        _pair_record("2026-01-01", "2026-01-31", 100, 30, is_estimated=True),
        _pair_record("2026-01-01", "2026-01-31", 100, 30, is_estimated=False),
    ]
    collapsed = _collapse_gas_pairs(pairs)
    assert len(collapsed) == 1
    assert collapsed[0]["is_estimated"] is False


def test_collapse_picks_larger_when_both_non_zero() -> None:
    """Defensive: if Mercury sends both with different non-zero values,
    pick the larger (likely the corrected/finalized read)."""
    pairs = [
        _pair_record("2026-01-01", "2026-01-31",  50, 15, is_estimated=True),
        _pair_record("2026-01-01", "2026-01-31",  75, 22, is_estimated=False),
    ]
    collapsed = _collapse_gas_pairs(pairs)
    assert len(collapsed) == 1
    assert collapsed[0]["consumption"] == 75


def test_collapse_passes_through_unpaired_records() -> None:
    """Single-group payloads (no estimate/actual structure) are returned
    chronologically, one entry per period."""
    pairs = [
        _pair_record("2026-02-01", "2026-02-28", 80, 20, is_estimated=False),
        _pair_record("2026-01-01", "2026-01-31", 60, 15, is_estimated=False),
    ]
    collapsed = _collapse_gas_pairs(pairs)
    assert len(collapsed) == 2
    assert collapsed[0]["invoice_to"] == "2026-01-31"
    assert collapsed[1]["invoice_to"] == "2026-02-28"


def test_collapse_empty_input_returns_empty() -> None:
    assert _collapse_gas_pairs([]) == []


# ----------------------------------------------------------------------------
# v1.5.2 — sum-baseline regression: most-recent imported entry must NOT be
# re-emitted (caused 460 × N compounding for the 27 March gas dashboard bar)
# ----------------------------------------------------------------------------


def test_monthly_entries_skip_anchor_at_cutoff_to_prevent_compounding() -> None:
    """Regression: when cutoff_ts equals the timestamp of an entry already
    in the recorder, that entry MUST be skipped. `energy_sum_start` is the
    recorder's cumulative sum *through* that anchor, so re-adding its kwh
    would double-count and inflate by N×kwh after N coordinator cycles —
    the v1.5.1 "164,220 kWh on 27 Mar" symptom."""
    march_anchor = datetime(2026, 3, 26, 11, 0, 0, tzinfo=timezone.utc)
    records = [
        _record("2026-03-27T00:00:00+13:00", 460.0, 156.28),  # anchor == cutoff
    ]
    energy, _cost, skipped = MercuryStatisticsImporter._build_monthly_entries(
        records,
        energy_sum_start=2864.0,    # recorder's sum through March 27 (incl.)
        cost_sum_start=900.0,
        cutoff_ts=march_anchor.timestamp(),
    )
    assert skipped == 0  # null_skip only counts parse failures
    assert energy == []  # no re-emission — would compound otherwise


def test_monthly_entries_emit_only_strictly_newer_than_cutoff() -> None:
    """Entries older than cutoff are skipped, equal-to-cutoff is skipped
    (already-imported boundary), strictly-newer is emitted with sum
    accumulating correctly from the carry-over."""
    feb_anchor = datetime(2026, 2, 25, 11, 0, 0, tzinfo=timezone.utc)
    records = [
        _record("2026-02-26T00:00:00+13:00", 397.0, 139.20),  # at cutoff
        _record("2026-03-27T00:00:00+13:00", 460.0, 156.28),  # > cutoff
    ]
    energy, _cost, skipped = MercuryStatisticsImporter._build_monthly_entries(
        records,
        energy_sum_start=2404.0,
        cost_sum_start=750.0,
        cutoff_ts=feb_anchor.timestamp(),
    )
    assert skipped == 0
    assert len(energy) == 1
    assert energy[0]["state"] == 460.0
    assert energy[0]["sum"] == 2404.0 + 460.0


def test_hourly_entries_skip_slot_at_cutoff_to_prevent_compounding() -> None:
    """Same regression as monthly, for the electricity hourly path. A slot
    whose timestamp equals cutoff_ts is already in the recorder's sum
    baseline; re-emitting it would compound by `kwh` per coordinator
    cycle until the slot exits the (formerly 3-day) window."""
    last_slot = datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)
    daily_records = []
    hourly_records = [
        {"datetime": "2026-04-28T22:00:00+12:00", "consumption": 1.5, "cost": 0.40},  # NZ-local 22:00 == 10:00 UTC
    ]
    energy, _cost, skipped = MercuryStatisticsImporter._build_hourly_entries(
        daily_records,
        hourly_records,
        energy_sum_start=1234.5,
        cost_sum_start=450.0,
        cutoff_ts=last_slot.timestamp(),
    )
    assert skipped == 0
    assert energy == []  # no re-emission
