"""Unit tests for the Mercury Energy NZ statistics importer."""

# pylint: disable=protected-access
from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.const import UnitOfEnergy
from homeassistant.util.unit_conversion import EnergyConverter

from custom_components.mercury_co_nz.const import DOMAIN
from custom_components.mercury_co_nz.statistics import MercuryStatisticsImporter

# Same regex the recorder enforces (recorder/statistics.py:VALID_STATISTIC_ID).
VALID_STATISTIC_ID = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_):(?!_)[\da-z_]+(?<!_)$")
NZ = ZoneInfo("Pacific/Auckland")


def _consume_coro(coro):
    """Drop a coroutine without awaiting it (silences ResourceWarning in pure tests)."""
    coro.close()
    return None


def _make_importer():
    """Construct an importer with a minimal mock hass that doesn't schedule tasks."""
    hass = MagicMock()
    hass.async_create_task = _consume_coro
    hass.config = MagicMock()
    hass.config.currency = "NZD"
    return MercuryStatisticsImporter(hass, "test@example.com")


# ----------------------------------------------------------------------------
# Pure-helper tests (no `hass` fixture needed)
# ----------------------------------------------------------------------------


def test_build_id_prefix_strips_dashes() -> None:
    assert (
        MercuryStatisticsImporter._build_id_prefix("0012345-67", "abc") == "0012345_67"
    )


def test_build_id_prefix_strips_dots() -> None:
    assert MercuryStatisticsImporter._build_id_prefix("acc.001", "abc") == "acc_001"


def test_build_id_prefix_lowercases() -> None:
    assert MercuryStatisticsImporter._build_id_prefix("ACC123", "abc") == "acc123"


def test_build_id_prefix_falls_back_to_email_hash() -> None:
    assert (
        MercuryStatisticsImporter._build_id_prefix(None, "abcdef12") == "acct_abcdef12"
    )
    assert MercuryStatisticsImporter._build_id_prefix("", "abcdef12") == "acct_abcdef12"


def test_build_metadata_energy_uses_kwh_unit_class() -> None:
    importer = _make_importer()
    energy_meta, _ = importer._build_metadata("acc123")
    assert energy_meta["unit_class"] == EnergyConverter.UNIT_CLASS
    assert energy_meta["unit_of_measurement"] == UnitOfEnergy.KILO_WATT_HOUR
    assert energy_meta["mean_type"] == StatisticMeanType.NONE
    assert energy_meta["has_sum"] is True


def test_build_metadata_cost_uses_nzd_no_unit_class() -> None:
    importer = _make_importer()
    _, cost_meta = importer._build_metadata("acc123")
    assert cost_meta["unit_class"] is None
    assert cost_meta["unit_of_measurement"] == "NZD"
    assert cost_meta["mean_type"] == StatisticMeanType.NONE
    assert cost_meta["has_sum"] is True


def test_build_metadata_source_matches_domain() -> None:
    importer = _make_importer()
    energy_meta, cost_meta = importer._build_metadata("acc123")
    assert energy_meta["source"] == DOMAIN
    assert cost_meta["source"] == DOMAIN


def test_build_metadata_statistic_id_matches_regex() -> None:
    importer = _make_importer()
    energy_meta, cost_meta = importer._build_metadata("acc123")
    assert VALID_STATISTIC_ID.match(energy_meta["statistic_id"]) is not None
    assert VALID_STATISTIC_ID.match(cost_meta["statistic_id"]) is not None


def test_build_metadata_name_matches_readme_template() -> None:
    """README documents the picker labels — they must match what _build_metadata writes."""
    importer = _make_importer()
    energy_meta, cost_meta = importer._build_metadata("acc123")
    assert energy_meta["name"] == "Mercury acc123 consumption"
    assert cost_meta["name"] == "Mercury acc123 cost"


def test_hourly_split_normal_day_24_entries() -> None:
    """A normal NZST day (no DST transition) produces 24 hourly entries."""
    records = [{"date": "2026-05-15T00:00:00", "consumption": 24.0, "cost": 12.0}]
    energy, cost, null = MercuryStatisticsImporter._build_hourly_entries(
        records, [], 0.0, 0.0, -1.0
    )
    assert len(energy) == 24
    assert len(cost) == 24
    assert null == 0
    # NZ midnight 2026-05-15 (NZST = UTC+12) -> 2026-05-14 12:00 UTC.
    assert energy[0]["start"] == datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    # 24 kWh / 24 h = 1.0 kWh per hour.
    assert energy[0]["state"] == pytest.approx(1.0)
    assert cost[0]["state"] == pytest.approx(0.5)
    # Sums increase monotonically; final sum equals the daily total.
    sums = [e["sum"] for e in energy]
    assert sums == sorted(sums)
    assert sums[-1] == pytest.approx(24.0)


def test_hourly_split_dst_end_25_hour_day() -> None:
    """First Sunday of April 2026 — NZDT ends, clocks go back, 25-hour day."""
    records = [{"date": "2026-04-05T00:00:00", "consumption": 25.0, "cost": 12.5}]
    energy, _cost, _ = MercuryStatisticsImporter._build_hourly_entries(
        records, [], 0.0, 0.0, -1.0
    )
    assert len(energy) == 25, f"expected 25 entries on DST-end day, got {len(energy)}"
    assert energy[0]["state"] == pytest.approx(1.0)
    # Last entry must NOT cross into the next NZ-local day.
    next_midnight_utc = datetime(2026, 4, 6, 0, 0, tzinfo=NZ).astimezone(timezone.utc)
    assert energy[-1]["start"] < next_midnight_utc


def test_hourly_split_dst_start_23_hour_day() -> None:
    """Last Sunday of September 2026 — NZDT begins, clocks spring forward, 23-hour day."""
    records = [{"date": "2026-09-27T00:00:00", "consumption": 23.0, "cost": 11.5}]
    energy, _cost, _ = MercuryStatisticsImporter._build_hourly_entries(
        records, [], 0.0, 0.0, -1.0
    )
    assert len(energy) == 23, f"expected 23 entries on DST-start day, got {len(energy)}"
    assert energy[0]["state"] == pytest.approx(1.0)


def test_hourly_split_skips_already_imported() -> None:
    """Strict less-than cutoff: entries at-or-after cutoff pass; entries before are skipped."""
    records = [
        {"date": "2026-05-14T00:00:00", "consumption": 24.0, "cost": 12.0},
        {"date": "2026-05-15T00:00:00", "consumption": 24.0, "cost": 12.0},
    ]
    # Cutoff = start of 2026-05-15 (NZ midnight = 2026-05-14 12:00 UTC).
    cutoff = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).timestamp()
    energy, _cost, _ = MercuryStatisticsImporter._build_hourly_entries(
        records, [], 0.0, 0.0, cutoff
    )
    # The 24 entries from 2026-05-14 are all strictly before cutoff -> skipped.
    # The 24 entries from 2026-05-15 start at exactly cutoff -> included (not strictly <).
    assert len(energy) == 24
    assert energy[0]["start"] >= datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def test_hourly_split_counts_null_records() -> None:
    """Records with None consumption or cost are counted (not silently dropped)."""
    records = [
        {"date": "2026-05-15T00:00:00", "consumption": None, "cost": 12.0},
        {"date": "2026-05-16T00:00:00", "consumption": 24.0, "cost": None},
        {"date": "2026-05-17T00:00:00", "consumption": 24.0, "cost": 12.0},
    ]
    energy, cost, null_count = MercuryStatisticsImporter._build_hourly_entries(
        records, [], 0.0, 0.0, -1.0
    )
    assert null_count == 2
    assert len(energy) == 24
    assert len(cost) == 24


def test_hourly_split_counts_unparseable_date() -> None:
    """Records with malformed `date` fields are counted as null skips, not raised."""
    records = [
        {"date": "not-a-date", "consumption": 24.0, "cost": 12.0},
        {"date": None, "consumption": 24.0, "cost": 12.0},
    ]
    energy, _cost, null_count = MercuryStatisticsImporter._build_hourly_entries(
        records, [], 0.0, 0.0, -1.0
    )
    assert null_count == 2
    assert len(energy) == 0


def test_hourly_records_emit_one_entry_each() -> None:
    """One hourly record produces exactly one StatisticData entry (no /24 division)."""
    hourly = [
        {"datetime": "2026-04-25T00:00:00+12:00", "consumption": 0.5, "cost": 0.10},
        {"datetime": "2026-04-25T01:00:00+12:00", "consumption": 0.7, "cost": 0.14},
        {"datetime": "2026-04-25T02:00:00+12:00", "consumption": 0.3, "cost": 0.06},
    ]
    energy, cost, null = MercuryStatisticsImporter._build_hourly_entries(
        [], hourly, 0.0, 0.0, -1.0,
    )
    assert len(energy) == 3
    assert len(cost) == 3
    assert null == 0
    # 2026-04-25 00:00 NZ (NZST = UTC+12) -> 2026-04-24 12:00 UTC.
    assert energy[0]["start"] == datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    assert energy[0]["state"] == pytest.approx(0.5)
    assert cost[0]["state"] == pytest.approx(0.10)
    # Cumulative sums follow raw values — no division applied.
    assert energy[2]["sum"] == pytest.approx(1.5)
    assert cost[2]["sum"] == pytest.approx(0.30)


def test_hourly_overrides_daily_for_same_nz_day() -> None:
    """When hourly covers an NZ day, the daily record for that day is suppressed."""
    daily = [
        {"date": "2026-04-25T00:00:00", "consumption": 24.0, "cost": 12.0},
        {"date": "2026-04-26T00:00:00", "consumption": 12.0, "cost": 6.0},
    ]
    # One hourly point inside 2026-04-25 NZ-local day suppresses the whole daily
    # record for that day; 2026-04-26 still gets the 24-entry split.
    hourly = [
        {"datetime": "2026-04-25T10:00:00+12:00", "consumption": 5.0, "cost": 2.5},
    ]
    energy, _cost, null = MercuryStatisticsImporter._build_hourly_entries(
        daily, hourly, 0.0, 0.0, -1.0,
    )
    assert null == 0
    # 1 hourly entry for 2026-04-25 + 24 daily-split entries for 2026-04-26 = 25.
    assert len(energy) == 25


def test_daily_only_path_unchanged_when_no_hourly() -> None:
    """Empty hourly_records preserves the original daily-split behaviour exactly."""
    daily = [{"date": "2026-05-15T00:00:00", "consumption": 24.0, "cost": 12.0}]
    energy, cost, null = MercuryStatisticsImporter._build_hourly_entries(
        daily, [], 0.0, 0.0, -1.0,
    )
    assert len(energy) == 24
    assert energy[0]["state"] == pytest.approx(1.0)
    assert cost[0]["state"] == pytest.approx(0.5)
    assert null == 0


def test_merged_sums_strictly_monotonic() -> None:
    """Cumulative sum is monotonic across mixed daily-split + hourly entries."""
    daily = [{"date": "2026-04-23T00:00:00", "consumption": 24.0, "cost": 12.0}]
    hourly = [
        {"datetime": "2026-04-25T10:00:00+12:00", "consumption": 0.5, "cost": 0.10},
        {"datetime": "2026-04-25T11:00:00+12:00", "consumption": 0.7, "cost": 0.14},
    ]
    energy, _cost, _null = MercuryStatisticsImporter._build_hourly_entries(
        daily, hourly, 0.0, 0.0, -1.0,
    )
    # Entries appear in chronological order; sums increase strictly monotonically.
    starts = [e["start"] for e in energy]
    assert starts == sorted(starts)
    sums = [e["sum"] for e in energy]
    assert all(b > a for a, b in zip(sums, sums[1:]))


# ----------------------------------------------------------------------------
# Integration smoke tests (use the `hass` fixture from
# pytest-homeassistant-custom-component)
# ----------------------------------------------------------------------------


async def test_async_update_first_run_calls_add_external_statistics(hass) -> None:
    """First run with empty recorder calls async_add_external_statistics twice."""
    importer = MercuryStatisticsImporter(hass, "test@example.com")
    await hass.async_block_till_done()

    # The recorder isn't set up in the bare hass fixture, so mock get_instance
    # to return a fake recorder whose async_add_executor_job just runs the callable.
    mock_recorder = MagicMock()

    async def _exec(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = _exec

    with patch(
        "custom_components.mercury_co_nz.statistics.get_instance",
        return_value=mock_recorder,
    ), patch(
        "custom_components.mercury_co_nz.statistics.get_last_statistics",
        return_value={},
    ), patch(
        "custom_components.mercury_co_nz.statistics.async_add_external_statistics"
    ) as mock_add:
        coordinator_data = {
            "bill_account_id": "ACC1",
            "extended_daily_usage_history": [
                {"date": "2026-05-15T00:00:00", "consumption": 24.0, "cost": 12.0}
            ],
        }
        await importer.async_update(coordinator_data)

    assert mock_add.call_count == 2
    metas = [call.args[1] for call in mock_add.call_args_list]
    stat_ids = sorted(m["statistic_id"] for m in metas)
    assert stat_ids == [
        f"{DOMAIN}:acc1_energy_consumption",
        f"{DOMAIN}:acc1_energy_cost",
    ]


async def test_async_update_id_flip_logs_error_and_does_not_write(hass, caplog) -> None:
    """Second run with a different prefix MUST NOT write and MUST log ERROR."""
    importer = MercuryStatisticsImporter(hass, "test@example.com")
    await hass.async_block_till_done()
    importer._id_prefix = "old_prefix"

    with patch(
        "custom_components.mercury_co_nz.statistics.async_add_external_statistics"
    ) as mock_add, caplog.at_level("ERROR"):
        coordinator_data = {
            "bill_account_id": "NEW123",
            "extended_daily_usage_history": [
                {"date": "2026-05-15T00:00:00", "consumption": 24.0, "cost": 12.0}
            ],
        }
        await importer.async_update(coordinator_data)

    mock_add.assert_not_called()
    assert any("ID changed" in rec.message for rec in caplog.records)


async def test_async_update_recorder_unavailable_increments_failure_count(
    hass,
) -> None:
    """`get_instance` raising KeyError must increment _consecutive_failures, not raise."""
    importer = MercuryStatisticsImporter(hass, "test@example.com")
    await hass.async_block_till_done()
    importer._id_prefix = "acc1"

    with patch(
        "custom_components.mercury_co_nz.statistics.get_instance",
        side_effect=KeyError("recorder not ready"),
    ):
        coordinator_data = {
            "bill_account_id": "acc1",
            "extended_daily_usage_history": [
                {"date": "2026-05-15T00:00:00", "consumption": 24.0, "cost": 12.0}
            ],
        }
        await importer.async_update(coordinator_data)
        assert importer._consecutive_failures == 1
        await importer.async_update(coordinator_data)
        assert importer._consecutive_failures == 2
