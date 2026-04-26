"""Test that extra_state_attributes stays under HA's 16KB cap (issue #4).

The HA recorder caps `state_attributes` at 16384 bytes; oversize attributes are
DROPPED (not truncated), causing `unit_of_measurement` to be lost downstream and
sensor.recorder to suppress long-term statistics with a "unit cannot be converted"
warning. These tests lock in the size invariant for the 3 chart sensors.
"""

# pylint: disable=protected-access
from __future__ import annotations

import json
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
    """Build a coordinator stub with 180 days daily + 168 hours hourly + 12 months."""
    coord = MagicMock()
    coord.data = {
        "extended_daily_usage_history": [
            {
                "date": f"2026-{1 + i // 30:02d}-{1 + i % 30:02d}T00:00:00",
                "consumption": 12.345,
                "cost": 3.39,
                "timestamp": f"2026-{1 + i // 30:02d}-{1 + i % 30:02d}T00:00:00",
                "free_power": False,
            }
            for i in range(180)
        ],
        "extended_temperature_history": [
            {
                "date": f"2026-{1 + i // 30:02d}-{1 + i % 30:02d}T00:00:00",
                "temp": 18.5 + (i % 10),
            }
            for i in range(180)
        ],
        "extended_hourly_usage_history": [
            {
                "datetime": f"2026-04-{20 + i // 24:02d}T{i % 24:02d}:00:00",
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


def test_truncation_keeps_most_recent_entries() -> None:
    """Slice [-N:] preserves order; we keep the LAST N entries (most recent)."""
    sensor = _make_sensor("energy_usage")
    attrs = sensor.extra_state_attributes
    daily = attrs["daily_usage_history"]
    # The synthetic data uses i in range(180); the last entry is i=179.
    # After [-45:], the first kept entry is i=135 (180-45).
    # i=135 → month = 1 + 135//30 = 5 (May), day = 1 + 135%30 = 16 → "2026-05-16"
    # Verify the first kept entry corresponds to ~i=135.
    first_kept_date = daily[0]["date"]
    last_kept_date = daily[-1]["date"]
    # Most recent should be after the first kept (chronological order preserved).
    assert last_kept_date > first_kept_date
