"""Test that extra_state_attributes stays under HA's 16KB cap (issue #4).

The HA recorder caps `state_attributes` at 16384 bytes; oversize attributes are
DROPPED (not truncated), causing `unit_of_measurement` to be lost downstream and
sensor.recorder to suppress long-term statistics with a "unit cannot be converted"
warning. These tests lock in the size invariant for the 3 chart sensors.
"""

# pylint: disable=protected-access
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.mercury_co_nz.const import (
    CHART_ATTRIBUTE_DAILY_DAYS,
    CHART_ATTRIBUTE_HOURLY_HOURS,
    DEFAULT_NAME,
)
from custom_components.mercury_co_nz.sensor import MercurySensor

# HA recorder cap from homeassistant/components/recorder/db_schema.py:
# SHARED_ATTRS_SCHEMA_LENGTH_LIMIT = 16384.
RECORDER_ATTRS_LIMIT = 16384

# Generous safety margin — leave 2KB headroom for HA's own JSON overhead and
# future additions to extra_state_attributes.
SAFETY_BUDGET = 14000


def _coordinator_with_synthetic_data():
    """Build a coordinator stub with 180 days daily + 168 hours hourly + 12 months.

    Uses real calendar dates (date(2026,1,1) + i days) so tests that compare
    or parse the date strings are exercising valid input.
    """
    base_date = date(2026, 1, 1)
    base_datetime = datetime(2026, 4, 20, 0, 0, 0)
    coord = MagicMock()
    coord.data = {
        "extended_daily_usage_history": [
            {
                "date": (base_date + timedelta(days=i)).isoformat() + "T00:00:00",
                "consumption": 12.345,
                "cost": 3.39,
                "timestamp": (base_date + timedelta(days=i)).isoformat() + "T00:00:00",
                "free_power": False,
            }
            for i in range(180)
        ],
        "extended_temperature_history": [
            {
                "date": (base_date + timedelta(days=i)).isoformat() + "T00:00:00",
                "temp": 18.5 + (i % 10),
            }
            for i in range(180)
        ],
        "extended_hourly_usage_history": [
            {
                "datetime": (base_datetime + timedelta(hours=i)).isoformat(),
                "consumption": 0.45,
                "cost": 0.12,
            }
            for i in range(168)
        ],
        "monthly_usage_history": [
            {"month": f"2024-{i:02d}", "consumption": 350.0, "cost": 95.5}
            for i in range(1, 13)
        ],
    }
    coord.last_update_success = True
    return coord


def _make_sensor(sensor_type: str) -> MercurySensor:
    coord = _coordinator_with_synthetic_data()
    return MercurySensor(coord, sensor_type, DEFAULT_NAME, "test@example.com")


@pytest.mark.parametrize("sensor_type", ["energy_usage", "total_usage", "current_bill"])
def test_chart_sensor_attributes_under_16kb(sensor_type: str) -> None:
    """All 3 chart sensors must serialize under HA's 16KB recorder cap."""
    sensor = _make_sensor(sensor_type)
    serialized = json.dumps(sensor.extra_state_attributes)
    assert len(serialized) < RECORDER_ATTRS_LIMIT, (
        f"{sensor_type} attributes are {len(serialized)} bytes; "
        f"cap is {RECORDER_ATTRS_LIMIT}"
    )


@pytest.mark.parametrize("sensor_type", ["energy_usage", "total_usage", "current_bill"])
def test_chart_sensor_attributes_under_safety_budget(sensor_type: str) -> None:
    """Stay comfortably under the cap to absorb future field additions."""
    sensor = _make_sensor(sensor_type)
    serialized = json.dumps(sensor.extra_state_attributes)
    assert len(serialized) < SAFETY_BUDGET, (
        f"{sensor_type} attributes are {len(serialized)} bytes; "
        f"safety budget is {SAFETY_BUDGET}"
    )


def test_temperature_history_no_longer_exposed() -> None:
    """`temperature_history` is dropped from attributes (unused by the card)."""
    sensor = _make_sensor("energy_usage")
    attrs = sensor.extra_state_attributes
    assert "temperature_history" not in attrs


def test_recent_temperatures_truncated_to_chart_window() -> None:
    """`recent_temperatures` is capped at CHART_ATTRIBUTE_DAILY_DAYS entries."""
    sensor = _make_sensor("energy_usage")
    attrs = sensor.extra_state_attributes
    assert len(attrs["recent_temperatures"]) == CHART_ATTRIBUTE_DAILY_DAYS


def test_daily_usage_history_truncated_to_chart_window() -> None:
    """daily_usage_history is capped at CHART_ATTRIBUTE_DAILY_DAYS entries."""
    sensor = _make_sensor("energy_usage")
    attrs = sensor.extra_state_attributes
    assert len(attrs["daily_usage_history"]) == CHART_ATTRIBUTE_DAILY_DAYS


def test_hourly_usage_history_truncated_to_chart_window() -> None:
    """hourly_usage_history is capped at CHART_ATTRIBUTE_HOURLY_HOURS entries."""
    sensor = _make_sensor("energy_usage")
    attrs = sensor.extra_state_attributes
    assert len(attrs["hourly_usage_history"]) == CHART_ATTRIBUTE_HOURLY_HOURS


def test_non_chart_sensor_has_no_history_attributes() -> None:
    """Non-chart sensors (e.g. plan_anytime_rate) don't get history attributes."""
    sensor = _make_sensor("plan_anytime_rate")
    attrs = sensor.extra_state_attributes
    for key in (
        "daily_usage_history",
        "hourly_usage_history",
        "monthly_usage_history",
        "recent_temperatures",
        "temperature_history",
    ):
        assert key not in attrs, f"non-chart sensor leaked {key} attribute"


def test_data_source_marker_preserved() -> None:
    """The `data_source` marker still reflects extended-vs-not (sanity check)."""
    sensor = _make_sensor("energy_usage")
    assert sensor.extra_state_attributes["data_source"] == "mercury_energy_api_extended"


def test_data_source_label_uses_non_extended_when_extended_is_empty_list() -> None:
    """If `extended_daily_usage_history` exists but is `[]`, fall back to
    non-extended AND label `data_source` correctly (regression guard).

    Original implementation used `.get(extended) or .get(non_extended)` which
    silently mislabelled the source when the extended key existed but was empty.
    Fixed by using explicit if/elif on truthy check.
    """
    coord = MagicMock()
    coord.data = {
        # Extended exists but is empty — should fall through to non-extended.
        "extended_daily_usage_history": [],
        "daily_usage_history": [
            {
                "date": "2026-04-20T00:00:00",
                "consumption": 1.0,
                "cost": 0.27,
                "timestamp": "2026-04-20T00:00:00",
                "free_power": False,
            }
        ],
    }
    coord.last_update_success = True
    sensor = MercurySensor(coord, "energy_usage", DEFAULT_NAME, "test@example.com")
    attrs = sensor.extra_state_attributes
    # Should use the non-extended source AND label data_source correctly.
    assert attrs["data_source"] == "mercury_energy_api", (
        "data_source mislabelled when extended key is empty list"
    )
    assert len(attrs["daily_usage_history"]) == 1


def test_truncation_keeps_most_recent_entries() -> None:
    """Slice [-N:] preserves order AND keeps the LAST N entries (most recent).

    Synthetic fixture uses date(2026,1,1) + i days for i in range(180):
    - Last entry: 2026-01-01 + 179 days = 2026-06-29.
    - First kept after [-45:]: 2026-01-01 + 135 days = 2026-05-16.
    Verify both endpoints are exact (not just that ordering is preserved).
    """
    sensor = _make_sensor("energy_usage")
    attrs = sensor.extra_state_attributes
    daily = attrs["daily_usage_history"]

    expected_first = (date(2026, 1, 1) + timedelta(days=180 - CHART_ATTRIBUTE_DAILY_DAYS)).isoformat() + "T00:00:00"
    expected_last = (date(2026, 1, 1) + timedelta(days=179)).isoformat() + "T00:00:00"

    assert daily[0]["date"] == expected_first, (
        f"first kept entry should be {expected_first}, got {daily[0]['date']}"
    )
    assert daily[-1]["date"] == expected_last, (
        f"last kept entry should be {expected_last}, got {daily[-1]['date']}"
    )


# ----------------------------------------------------------------------------
# v1.6.0 — gas chart attribute exposure (gas-monthly-summary-card.js)
# ----------------------------------------------------------------------------


def _coordinator_with_gas_data():
    """Build a coordinator stub holding only gas-side data, mirroring what
    coordinator.py:169-176 produces after `gas_` prefixing."""
    coord = MagicMock()
    coord.data = {
        "gas_monthly_usage_history": [
            {
                "date": "2026-02-26",
                "consumption": 397.0,
                "cost": 139.20,
                "free_power": False,
                "invoice_from": "2026-01-31",
                "invoice_to": "2026-02-26",
                "is_estimated": True,
                "read_type": "estimate",
            },
            {
                "date": "2026-03-27",
                "consumption": 460.0,
                "cost": 156.28,
                "free_power": False,
                "invoice_from": "2026-02-27",
                "invoice_to": "2026-03-27",
                "is_estimated": False,
                "read_type": "actual",
            },
        ],
        "gas_monthly_usage": 4842.0,
        "gas_monthly_cost": 1499.42,
        # Electricity data NOT present — the gas card must not depend on it.
    }
    coord.last_update_success = True
    return coord


def test_gas_monthly_usage_sensor_exposes_chart_history() -> None:
    """The gas_monthly_usage sensor must expose gas_monthly_usage_history as
    an extra_state_attribute so gas-monthly-summary-card.js can read it via
    hass.states[entity_id].attributes.gas_monthly_usage_history.
    """
    coord = _coordinator_with_gas_data()
    sensor = MercurySensor(coord, "gas_monthly_usage", DEFAULT_NAME, "test@example.com")

    attrs = sensor.extra_state_attributes
    assert attrs["gas_monthly_usage_history"] == coord.data["gas_monthly_usage_history"]
    assert attrs["gas_monthly_data_points"] == 2
    assert attrs["gas_monthly_total_usage"] == 4842.0
    assert attrs["gas_monthly_total_cost"] == 1499.42

    # LOAD-BEARING for per-bar coloring — the card maps is_estimated → color.
    assert attrs["gas_monthly_usage_history"][0]["is_estimated"] is True
    assert attrs["gas_monthly_usage_history"][1]["is_estimated"] is False


def test_gas_monthly_usage_native_value_reads_total() -> None:
    """The sensor's native_value must be the kWh scalar, not the history list."""
    coord = _coordinator_with_gas_data()
    sensor = MercurySensor(coord, "gas_monthly_usage", DEFAULT_NAME, "test@example.com")
    assert sensor.native_value == 4842.0


def test_electricity_sensors_do_not_get_gas_attributes() -> None:
    """Issue #4 isolation: gas attributes must NOT bleed onto electricity
    chart sensors — they're already near the 14KB attribute-size budget."""
    coord = _coordinator_with_synthetic_data()
    coord.data["gas_monthly_usage_history"] = [
        {
            "date": "2026-03-27", "consumption": 460.0, "cost": 156.28,
            "invoice_from": "2026-02-27", "invoice_to": "2026-03-27",
            "is_estimated": False, "read_type": "actual", "free_power": False,
        }
    ]
    coord.data["gas_monthly_usage"] = 460.0
    coord.data["gas_monthly_cost"] = 156.28

    sensor = MercurySensor(coord, "energy_usage", DEFAULT_NAME, "test@example.com")
    attrs = sensor.extra_state_attributes

    assert "gas_monthly_usage_history" not in attrs
    assert "gas_monthly_data_points" not in attrs
    assert "gas_monthly_total_usage" not in attrs
    assert "gas_monthly_total_cost" not in attrs


def test_gas_sensor_stays_under_safety_budget() -> None:
    """Gas history is ~10 entries × ~250 bytes ≈ 2.5KB. Verify the gas chart
    sensor's attributes are well under the 14KB safety budget even with a
    full year of data."""
    base_date = date(2026, 1, 1)
    coord = MagicMock()
    coord.data = {
        "gas_monthly_usage_history": [
            {
                "date": (base_date + timedelta(days=30 * i)).isoformat(),
                "consumption": 400.0 + i * 50,
                "cost": 130.50 + i * 15,
                "free_power": False,
                "invoice_from": (base_date + timedelta(days=30 * i - 28)).isoformat(),
                "invoice_to": (base_date + timedelta(days=30 * i)).isoformat(),
                "is_estimated": (i % 2 == 0),
                "read_type": "estimate" if (i % 2 == 0) else "actual",
            }
            for i in range(12)
        ],
        "gas_monthly_usage": 5400.0,
        "gas_monthly_cost": 1700.0,
    }
    coord.last_update_success = True

    sensor = MercurySensor(coord, "gas_monthly_usage", DEFAULT_NAME, "test@example.com")
    serialized = json.dumps(sensor.extra_state_attributes)
    assert len(serialized) < SAFETY_BUDGET, (
        f"gas_monthly_usage attributes are {len(serialized)} bytes; "
        f"safety budget is {SAFETY_BUDGET}"
    )


# ----------------------------------------------------------------------------
# v1.6.1 — has_entity_name + clean entity_id slug regression guard
# ----------------------------------------------------------------------------


def test_v1_6_1_has_entity_name_is_true() -> None:
    """v1.6.1 sets has_entity_name=True so HA composes friendly_name as
    `{device.name} {_attr_name}` automatically (clean slug, no doubled
    'Mercury NZ' or email-included entity_ids)."""
    sensor = _make_sensor("gas_monthly_usage")
    assert sensor._attr_has_entity_name is True


def test_v1_6_1_attr_name_is_just_sensor_suffix() -> None:
    """v1.6.1 strips the device-name prefix from `_attr_name`. HA combines
    `device.name` + `_attr_name` for display, so `_attr_name` should be
    just the per-sensor suffix (e.g. 'Gas Monthly Usage'), not
    'Mercury NZ Gas Monthly Usage'."""
    sensor = _make_sensor("gas_monthly_usage")
    assert sensor._attr_name == "Gas Monthly Usage"
    assert "Mercury NZ" not in sensor._attr_name

    elec = _make_sensor("energy_usage")
    assert elec._attr_name == "Energy Usage"
    assert "Mercury NZ" not in elec._attr_name


def test_v1_6_1_device_name_no_longer_includes_email() -> None:
    """v1.6.1 `device_info.name` is just the config-entry name (e.g.
    'Mercury NZ') — the email is dropped so HA's entity_id slug doesn't
    pull the email into every new entity. Multi-account users are still
    distinguished by the `(DOMAIN, email)` identifier tuple."""
    sensor = _make_sensor("gas_monthly_usage")
    info = sensor.device_info
    assert info["name"] == DEFAULT_NAME  # "Mercury NZ"
    assert "test@example.com" not in info["name"]
    assert "@" not in info["name"]
    # Identifier tuple keeps email so the device is uniquely keyed.
    assert info["identifiers"] == {("mercury_co_nz", "test@example.com")}
