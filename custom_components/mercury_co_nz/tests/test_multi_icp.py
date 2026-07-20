"""Tests for v2.0.0 multi-ICP support.

Covers:
- LOAD-BEARING back-compat: primary-ICP unique_id, statistic_id, Store key all
  match v1.5.x byte-for-byte (single-ICP users see zero entity_id changes).
- Secondary-ICP behavior: ICP-token-prefixed unique_ids, statistic_ids, Store keys.
- ICP-vs-account scope split: SENSOR_TYPES bifurcation between ICP_SCOPED and
  account-scoped (single instance per account) sensors.
- _sanitize_for_key edge cases.
"""

# pylint: disable=protected-access
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.mercury_co_nz.const import (
    DOMAIN,
    ICP_SCOPED_SENSOR_TYPES,
    SENSOR_TYPES,
    STATISTICS_COST_SUFFIX,
    STATISTICS_ENERGY_SUFFIX,
)
from custom_components.mercury_co_nz.statistics import (
    MercuryStatisticsImporter,
    _sanitize_for_key,
)


def _consume_coro(coro):
    coro.close()


def _hass() -> MagicMock:
    h = MagicMock()
    h.async_create_task = _consume_coro
    h.config.currency = "NZD"
    return h


# ----------------------------------------------------------------------------
# LOAD-BEARING: Primary-ICP back-compat invariants
# ----------------------------------------------------------------------------


def test_primary_electricity_store_key_matches_v15x_exactly() -> None:
    """LOAD-BEARING: primary electricity ICP Store key MUST equal v1.5.x format."""
    importer = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="electricity",
        service_id="ICP_001",
        is_primary=True,
    )
    # v1.5.x format: f"{DOMAIN}_statistics_{email_hash}" (no fuel suffix, no icp suffix)
    assert importer._store.key == f"{DOMAIN}_statistics_{importer._email_hash}"


def test_primary_gas_store_key_matches_v15x_exactly() -> None:
    """LOAD-BEARING: primary gas ICP Store key MUST equal v1.5.x format."""
    importer = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="gas",
        service_id="ICP_GAS_001",
        is_primary=True,
    )
    # v1.5.x format: f"{DOMAIN}_statistics_gas_{email_hash}" (fuel suffix, no icp suffix)
    assert importer._store.key == f"{DOMAIN}_statistics_gas_{importer._email_hash}"


def test_primary_electricity_statistic_id_matches_v15x_exactly() -> None:
    """LOAD-BEARING: primary electricity statistic_id MUST equal v1.5.x format —
    Energy Dashboard's existing series for single-ICP users continue accruing
    without 'ID changed' ERROR.
    """
    importer = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="electricity",
        service_id="ICP_001",
        is_primary=True,
    )
    energy_meta, cost_meta = importer._build_metadata("acc1")
    assert energy_meta["statistic_id"] == f"{DOMAIN}:acc1_{STATISTICS_ENERGY_SUFFIX}"
    assert cost_meta["statistic_id"] == f"{DOMAIN}:acc1_{STATISTICS_COST_SUFFIX}"


def test_primary_electricity_default_constructor_unchanged() -> None:
    """Default-args construction (no service_id, is_primary=True default) MUST
    produce the same byte-for-byte output as v1.5.x — single-arg construction
    in old code paths keeps working."""
    importer = MercuryStatisticsImporter(_hass(), "user@example.com")
    energy_meta, _ = importer._build_metadata("acc1")
    assert "energy_consumption" in energy_meta["statistic_id"]
    assert "icp_" not in energy_meta["statistic_id"]
    assert importer._store.key == f"{DOMAIN}_statistics_{importer._email_hash}"


# ----------------------------------------------------------------------------
# Secondary-ICP behavior — token in keys/IDs
# ----------------------------------------------------------------------------


def test_secondary_electricity_store_key_includes_icp_token() -> None:
    importer = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="electricity",
        service_id="ICP_002",
        is_primary=False,
    )
    assert "icp_002" in importer._store.key.lower()
    # Different from primary
    primary = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="electricity",
        service_id="ICP_001",
        is_primary=True,
    )
    assert importer._store.key != primary._store.key


def test_secondary_electricity_statistic_id_includes_icp_token() -> None:
    importer = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="electricity",
        service_id="ICP_002",
        is_primary=False,
    )
    energy_meta, cost_meta = importer._build_metadata("acc1")
    assert "icp_002" in energy_meta["statistic_id"].lower()
    assert "icp_002" in cost_meta["statistic_id"].lower()


def test_secondary_gas_has_compound_fuel_and_icp_suffix() -> None:
    """Gas + non-primary ICP must have BOTH fuel and icp suffixes in Store key."""
    importer = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="gas",
        service_id="ICP_GAS_002",
        is_primary=False,
    )
    assert "_gas_" in importer._store.key
    assert "icp_gas_002" in importer._store.key.lower()


def test_secondary_name_says_icp_token() -> None:
    importer = MercuryStatisticsImporter(
        _hass(), "user@example.com",
        fuel_type="electricity",
        service_id="ICP_002",
        is_primary=False,
    )
    energy_meta, _ = importer._build_metadata("acc1")
    assert "icp_002" in energy_meta["name"].lower()


# ----------------------------------------------------------------------------
# ICP-vs-account scope split
# ----------------------------------------------------------------------------


def test_icp_scoped_sensor_set_count() -> None:
    """ICP_SCOPED_SENSOR_TYPES must contain exactly the 14 per-meter keys."""
    assert len(ICP_SCOPED_SENSOR_TYPES) == 14


def test_account_scoped_sensors_excluded_from_icp_set() -> None:
    """Bill_*, weekly_*, monthly_billing_*, customer_id are account-level —
    NOT in ICP_SCOPED. Multi-ICP users get one instance, not N copies."""
    account_scoped_examples = (
        "bill_account_id", "bill_balance", "bill_due_amount",
        "weekly_start_date", "weekly_end_date",
        "monthly_billing_start_date", "monthly_billing_end_date",
        "customer_id",
    )
    for key in account_scoped_examples:
        if key in SENSOR_TYPES:
            assert key not in ICP_SCOPED_SENSOR_TYPES, (
                f"{key} is account-level — must NOT be in ICP_SCOPED_SENSOR_TYPES"
            )


def test_icp_scoped_keys_are_subset_of_sensor_types() -> None:
    """Every key in ICP_SCOPED_SENSOR_TYPES must exist in SENSOR_TYPES (no typos)."""
    assert ICP_SCOPED_SENSOR_TYPES.issubset(SENSOR_TYPES.keys())


def test_plan_icp_number_is_icp_scoped() -> None:
    """plan_icp_number IS the ICP identifier — must be ICP-scoped, not account."""
    assert "plan_icp_number" in ICP_SCOPED_SENSOR_TYPES


# ----------------------------------------------------------------------------
# _sanitize_for_key edge cases
# ----------------------------------------------------------------------------


def test_sanitize_handles_dashes() -> None:
    assert _sanitize_for_key("ICP-001-A") == "icp_001_a"


def test_sanitize_handles_dots() -> None:
    assert _sanitize_for_key("0001.123.456") == "0001_123_456"


def test_sanitize_lowercases() -> None:
    assert _sanitize_for_key("ABCDEF") == "abcdef"


def test_sanitize_none_falls_back_to_primary() -> None:
    assert _sanitize_for_key(None) == "primary"
    assert _sanitize_for_key("") == "primary"


def test_sanitize_real_nz_icp_format() -> None:
    """Realistic NZ ICP number: 15-char alphanumeric like 0001263891UN390."""
    assert _sanitize_for_key("0001263891UN390") == "0001263891un390"
