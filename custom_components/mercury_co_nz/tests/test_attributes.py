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
