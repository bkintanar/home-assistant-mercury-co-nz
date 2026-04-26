"""Unit tests for `MercuryAPI._normalize_plans_data` and the get_electricity_plans
diagnostic logging (issue #6).

The normalization tests guard the cents-to-NZD conversion. If they fail because
someone removed the `/100.0` divisor, HACS dynamic_energy_cost would silently
produce costs that are 100x too high.

The diagnostic-logging tests guard the v1.2.1 diagnostic INFO lines that surface
which of pymercury's three internal failure paths (A/B/C) fired when
get_electricity_plans returns None. Without these logs, the user has no way
to distinguish failure modes.
"""

# pylint: disable=protected-access
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mercury_co_nz.mercury_api import MercuryAPI


def _api() -> MercuryAPI:
    """Construct a MercuryAPI without running __init__ (no session/email needed)."""
    return MercuryAPI.__new__(MercuryAPI)


def _ns(**kwargs) -> SimpleNamespace:
    """Build a SimpleNamespace so `hasattr(__dict__)` succeeds in the helper."""
    return SimpleNamespace(**kwargs)


def test_normalize_anytime_rate_cents_form_with_measure() -> None:
    """Defensive: if Mercury ever serves cents form ('27.5' with measure='c/kWh'),
    the helper detects 'c' in the measure and divides by 100."""
    out = _api()._normalize_plans_data(
        _ns(anytime_rate="27.5", anytime_rate_measure="c/kWh")
    )
    assert out["anytime_rate"] == 0.275


def test_normalize_daily_fixed_charge_dollar_string() -> None:
    """Mercury's actual format: '$1.37' string in dollars-per-day."""
    out = _api()._normalize_plans_data(_ns(daily_fixed_charge="$1.37"))
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
    the helper falls through to `plans_dict = plans_data`. Use Mercury's actual
    string format ('$0.30').
    """
    raw = {"anytime_rate": "$0.30", "current_plan_name": "Low User"}
    out = _api()._normalize_plans_data(raw)
    assert out["anytime_rate"] == 0.3
    assert out["current_plan_name"] == "Low User"


def test_normalize_returns_empty_on_none_input() -> None:
    """None / falsy input short-circuits to {}."""
    assert _api()._normalize_plans_data(None) == {}
    assert _api()._normalize_plans_data({}) == {}


def test_normalize_full_record_round_trip() -> None:
    """Sanity check on a realistic Mercury record — every field present.

    Uses Mercury's actual string format ('$X.XXXX') for the rate fields.
    """
    plans = _ns(
        anytime_rate="$0.2995",
        daily_fixed_charge="$1.49",
        current_plan_id="ANYTIME_2024",
        current_plan_name="Anytime",
        current_plan_description="Best for anytime users",
        current_plan_usage_type="Standard",
        icp_number="0000123456ABC78",
        anytime_rate_measure="$/kWh",
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
    assert out["anytime_rate_measure"] == "$/kWh"
    assert out["can_change_plan"] == "yes"
    assert out["is_pending_plan_change"] == "no"


# ----------------------------------------------------------------------------
# v1.2.1 — Diagnostic logging tests for get_electricity_plans (issue #6 follow-up)
# ----------------------------------------------------------------------------


def _build_get_electricity_plans_fixture(
    *,
    plans_return,
    services_return,
    complete_data_identifier=None,
    service_id="SVC123",
):
    """Construct a MercuryAPI instance + mocks for get_electricity_plans.

    The returned tuple is `(api, complete_data_mock, services_mock)` so tests
    can configure return values for both pymercury internal calls
    (`get_complete_account_data` and `_api_client.get_services`) plus the
    plans call itself.
    """
    api = _api()
    api._authenticated = True

    elec_service = MagicMock()
    elec_service.is_electricity = True
    elec_service.service_id = service_id
    elec_service.service_group = "electricity"
    elec_service.raw_data = {"identifier": complete_data_identifier}

    complete_data = MagicMock()
    complete_data.customer_id = "CUST1"
    complete_data.account_ids = ["ACC1"]
    complete_data.services = [elec_service]

    api_client_mock = MagicMock()
    api_client_mock.get_electricity_plans = MagicMock(return_value=plans_return)
    api_client_mock.get_services = MagicMock(return_value=services_return)

    client_mock = MagicMock()
    client_mock.get_complete_account_data = MagicMock(return_value=complete_data)
    client_mock._api_client = api_client_mock

    api._client = client_mock
    return api


@pytest.mark.asyncio
async def test_diagnostic_logs_emit_complete_data_identifier(caplog) -> None:
    """The first diagnostic INFO line surfaces `identifier` from complete_data.services."""
    api = _build_get_electricity_plans_fixture(
        plans_return=None,
        services_return=[],
        complete_data_identifier="0000123456ABC78",
        service_id="SVC123",
    )
    with caplog.at_level(logging.INFO):
        result = await api.get_electricity_plans()

    assert result == {}
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        "service_id=SVC123" in m
        and "identifier-from-complete_data='0000123456ABC78'" in m
        for m in msgs
    ), f"diagnostic log line not found in: {msgs}"


@pytest.mark.asyncio
async def test_diagnostic_logs_emit_get_services_result(caplog) -> None:
    """The second diagnostic INFO line surfaces what pymercury's get_services returns."""
    matching_service = MagicMock()
    matching_service.service_id = "SVC123"
    matching_service.service_group = "electricity"
    matching_service.raw_data = {"identifier": "ICP_FROM_GETSERVICES"}

    api = _build_get_electricity_plans_fixture(
        plans_return=None,
        services_return=[matching_service],
        complete_data_identifier="ICP_FROM_COMPLETEDATA",
        service_id="SVC123",
    )
    with caplog.at_level(logging.INFO):
        result = await api.get_electricity_plans()

    assert result == {}
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        "get_services returned 1 service(s)" in m
        and "matched-for-our-service_id=True" in m
        and "identifier-from-get_services='ICP_FROM_GETSERVICES'" in m
        for m in msgs
    ), f"get_services diagnostic line not found in: {msgs}"


@pytest.mark.asyncio
async def test_diagnostic_logs_distinguish_no_services(caplog) -> None:
    """If get_services returns empty list, diagnostic shows '0 service(s)' / no match."""
    api = _build_get_electricity_plans_fixture(
        plans_return=None,
        services_return=[],
        complete_data_identifier="ANY",
        service_id="SVC123",
    )
    with caplog.at_level(logging.INFO):
        await api.get_electricity_plans()

    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        "get_services returned 0 service(s)" in m
        and "matched-for-our-service_id=False" in m
        for m in msgs
    ), f"empty-services diagnostic not found in: {msgs}"


@pytest.mark.asyncio
async def test_get_electricity_plans_returns_empty_when_pymercury_returns_none(
    caplog,
) -> None:
    """When pymercury silently returns None, wrapper returns {} and logs the failure-mode hint."""
    api = _build_get_electricity_plans_fixture(
        plans_return=None,
        services_return=[],
        complete_data_identifier=None,
    )
    with caplog.at_level(logging.WARNING):
        result = await api.get_electricity_plans()

    assert result == {}
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        "No electricity plans data returned" in m
        and "(A) get_services empty / no match" in m
        for m in msgs
    ), f"failure-mode hint not found in WARNING logs: {msgs}"


# ----------------------------------------------------------------------------
# v1.2.2 — _parse_rate_amount helper tests + regression for '$0.2737' bug
# ----------------------------------------------------------------------------


def test_parse_rate_amount_dollar_string() -> None:
    """The actual format Mercury returns: '$0.2737' → 0.2737."""
    assert MercuryAPI._parse_rate_amount("$0.2737", "$/kWh") == 0.2737


def test_parse_rate_amount_dollar_with_thousands_separator() -> None:
    """Defensive: '$1,234.56' → 1234.56."""
    assert MercuryAPI._parse_rate_amount("$1,234.56", "$/day") == 1234.56


def test_parse_rate_amount_cents_with_c_suffix() -> None:
    """Defensive: if Mercury ever serves '27.5c' with measure='c/kWh' → 0.275 NZD."""
    assert MercuryAPI._parse_rate_amount("27.5c", "c/kWh") == 0.275


def test_parse_rate_amount_cents_with_explicit_measure() -> None:
    """A bare numeric '27.5' string with measure='c/kWh' is interpreted as cents → 0.275 NZD."""
    assert MercuryAPI._parse_rate_amount("27.5", "c/kWh") == 0.275


def test_parse_rate_amount_numeric_dollars_passthrough() -> None:
    """A bare float (no measure) is treated as already canonical dollars."""
    assert MercuryAPI._parse_rate_amount(0.2737, None) == 0.2737


def test_parse_rate_amount_returns_none_for_none() -> None:
    assert MercuryAPI._parse_rate_amount(None, "$/kWh") is None


def test_parse_rate_amount_returns_none_for_unparseable(caplog) -> None:
    """Malformed input → None + WARNING log."""
    with caplog.at_level(logging.WARNING):
        result = MercuryAPI._parse_rate_amount("not a number", "$/kWh")
    assert result is None
    assert any("could not parse rate" in r.getMessage() for r in caplog.records)


def test_parse_rate_amount_zero_is_preserved() -> None:
    """Free-power period (0.0) must NOT become None."""
    assert MercuryAPI._parse_rate_amount("$0.00", "$/kWh") == 0.0
    assert MercuryAPI._parse_rate_amount(0, "$/kWh") == 0.0


def test_normalize_handles_dollar_string_anytime_rate() -> None:
    """Regression test for the bug from issue #6 logs.

    Verifies that Mercury's actual `'$0.2737'` format does NOT raise ValueError
    inside `_normalize_plans_data` and produces the correct float.
    """
    plans = _ns(
        anytime_rate="$0.2737",
        anytime_rate_measure="$/kWh",
        daily_fixed_charge="$1.49",
        current_plan_name="Anytime",
    )
    out = _api()._normalize_plans_data(plans)
    assert out != {}, "normalize must not return empty dict for valid input"
    assert out["anytime_rate"] == 0.2737
    assert out["daily_fixed_charge"] == 1.49
    assert out["current_plan_name"] == "Anytime"
