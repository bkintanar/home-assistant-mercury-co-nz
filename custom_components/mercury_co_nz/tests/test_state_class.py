"""Test invariants on SENSOR_TYPES state_class assignments (issue #4 follow-up).

Background: HA's `total_increasing` contract requires monotonic non-decreasing
values; decreases trigger "unexpected dip" warnings AND corrupt the
`total_increasing` long-term-stat accumulator. Several Mercury sensors expose
WINDOWED sums (last 7 days, last 2 months) — which decrease when the API
window rolls — and were incorrectly tagged `total_increasing` since v1.0.0,
silently producing bad stats and contributing to the recorder.py:335/:368
unit-mix warnings the user reported after v1.2.3 deployed.

These tests lock in the corrected state_class assignments and catch future
regressions where someone adds a kWh/$ sensor without a state_class (which
silently disables long-term statistics).
"""

from __future__ import annotations

from custom_components.mercury_co_nz.const import SENSOR_TYPES


def test_windowed_sum_sensors_not_total_increasing() -> None:
    """Windowed-sum sensors must NOT use total_increasing.

    Mercury exposes these as trailing-window aggregates whose value decreases
    when the oldest sample drops out of the window — that breaks
    total_increasing's monotonic contract.
    """
    windowed_sum_sensors = ("total_usage", "hourly_usage", "monthly_usage")
    for sensor_type in windowed_sum_sensors:
        config = SENSOR_TYPES[sensor_type]
        assert config["state_class"] != "total_increasing", (
            f"{sensor_type} is a windowed sum (value decreases when window rolls); "
            "state_class=total_increasing violates HA's monotonic contract."
        )


def test_windowed_sum_sensors_use_total() -> None:
    """The chosen replacement is `total`, not `measurement` or None.

    `total` keeps long-term statistics enabled (unlike `measurement` for
    energy device_class) and tolerates up/down values (unlike total_increasing).
    """
    windowed_sum_sensors = ("total_usage", "hourly_usage", "monthly_usage")
    for sensor_type in windowed_sum_sensors:
        assert SENSOR_TYPES[sensor_type]["state_class"] == "total", (
            f"{sensor_type} state_class should be 'total' to participate in "
            "long-term statistics with non-monotonic values."
        )


def test_state_class_present_for_numeric_sensors() -> None:
    """Numeric sensors with kWh/$/rate units must declare a state_class.

    Without it, HA silently skips long-term statistics — same failure mode the
    user just hit, but harder to diagnose because there's no warning at all.
    """
    units_requiring_state_class = ("kWh", "$", "NZD/kWh", "NZD/day")
    for sensor_type, config in SENSOR_TYPES.items():
        if config.get("unit") in units_requiring_state_class:
            assert config.get("state_class") is not None, (
                f"{sensor_type} has unit {config['unit']!r} but no state_class — "
                "long-term statistics will be silently skipped."
            )
