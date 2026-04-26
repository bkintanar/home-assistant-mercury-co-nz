"""Unit tests for `MercuryAPI._normalize_plans_data` (issue #6).

These tests guard the cents-to-NZD conversion. If they fail because someone
removed the `/100.0` divisor, HACS dynamic_energy_cost would silently produce
costs that are 100x too high.
"""

# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

from custom_components.mercury_co_nz.mercury_api import MercuryAPI


def _api() -> MercuryAPI:
    """Construct a MercuryAPI without running __init__ (no session/email needed)."""
    return MercuryAPI.__new__(MercuryAPI)


def _ns(**kwargs) -> SimpleNamespace:
    """Build a SimpleNamespace so `hasattr(__dict__)` succeeds in the helper."""
    return SimpleNamespace(**kwargs)


def test_normalize_converts_anytime_rate_cents_to_nzd() -> None:
    """27.5 NZ cents/kWh -> 0.275 NZD/kWh."""
    out = _api()._normalize_plans_data(_ns(anytime_rate=27.5))
    assert out["anytime_rate"] == 0.275


def test_normalize_converts_daily_fixed_charge_cents_to_nzd() -> None:
    """137.0 NZ cents/day -> 1.37 NZD/day."""
    out = _api()._normalize_plans_data(_ns(daily_fixed_charge=137.0))
    assert out["daily_fixed_charge"] == 1.37


def test_normalize_preserves_zero_rate() -> None:
    """A free-power period (0.0) must NOT become None — `is not None` guard."""
    out = _api()._normalize_plans_data(_ns(anytime_rate=0.0, daily_fixed_charge=0.0))
    assert out["anytime_rate"] == 0.0
    assert out["daily_fixed_charge"] == 0.0


def test_normalize_returns_none_for_missing_rate() -> None:
    """When pymercury hasn't populated the rate, output is None (sensor: unknown)."""
    out = _api()._normalize_plans_data(_ns(current_plan_name="Anytime"))
    assert out["anytime_rate"] is None
    assert out["daily_fixed_charge"] is None
    assert out["current_plan_name"] == "Anytime"


def test_normalize_serializes_pending_plan_change() -> None:
    """Booleans serialise to `yes`/`no` strings (sensor-only platform)."""
    yes_out = _api()._normalize_plans_data(
        _ns(is_pending_plan_change=True, can_change_plan=True)
    )
    no_out = _api()._normalize_plans_data(
        _ns(is_pending_plan_change=False, can_change_plan=False)
    )
    assert yes_out["is_pending_plan_change"] == "yes"
    assert yes_out["can_change_plan"] == "yes"
    assert no_out["is_pending_plan_change"] == "no"
    assert no_out["can_change_plan"] == "no"


def test_normalize_handles_dict_input() -> None:
    """If pymercury hands us a plain dict, the third fallback branch handles it.

    A plain `dict` has no instance `__dict__` and no `to_dict()` method, so
    the helper falls through to `plans_dict = plans_data`.
    """
    raw = {"anytime_rate": 30.0, "current_plan_name": "Low User"}
    out = _api()._normalize_plans_data(raw)
    assert out["anytime_rate"] == 0.3
    assert out["current_plan_name"] == "Low User"


def test_normalize_returns_empty_on_none_input() -> None:
    """None / falsy input short-circuits to {}."""
    assert _api()._normalize_plans_data(None) == {}
    assert _api()._normalize_plans_data({}) == {}


def test_normalize_full_record_round_trip() -> None:
    """Sanity check on a realistic input — every field present."""
    plans = _ns(
        anytime_rate=29.95,
        daily_fixed_charge=149.0,
        current_plan_id="ANYTIME_2024",
        current_plan_name="Anytime",
        current_plan_description="Best for anytime users",
        current_plan_usage_type="Standard",
        icp_number="0000123456ABC78",
        anytime_rate_measure="c/kWh",
        plan_change_date="",
        can_change_plan=True,
        is_pending_plan_change=False,
    )
    out = _api()._normalize_plans_data(plans)
    assert out["anytime_rate"] == 0.2995
    assert out["daily_fixed_charge"] == 1.49
    assert out["current_plan_id"] == "ANYTIME_2024"
    assert out["current_plan_name"] == "Anytime"
    assert out["icp_number"] == "0000123456ABC78"
    assert out["anytime_rate_measure"] == "c/kWh"
    assert out["can_change_plan"] == "yes"
    assert out["is_pending_plan_change"] == "no"
