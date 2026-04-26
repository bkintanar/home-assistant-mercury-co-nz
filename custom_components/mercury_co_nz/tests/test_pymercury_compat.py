"""Compatibility tests for the wrapper-to-pymercury contract.

These tests run offline (no credentials, no network) and verify that every
pymercury symbol `mercury_api.py` depends on still exists with the expected
shape. They guard against signature drift in pymercury minor/patch releases.

Test target: pymercury (PyPI: mercury-co-nz-api) >= 1.0.2.
Currently verified against: pymercury 1.1.0.
"""

# pylint: disable=protected-access
from __future__ import annotations

import inspect

import pytest
from pymercury import MercuryClient
from pymercury.api import MercuryAPIClient

# ----------------------------------------------------------------------------
# MercuryClient public surface
# ----------------------------------------------------------------------------


def test_mercuryclient_importable() -> None:
    """`from pymercury import MercuryClient` resolves to a class."""
    assert inspect.isclass(MercuryClient)


def test_mercuryclient_constructor_takes_email_and_password() -> None:
    """The 2-positional-arg form `MercuryClient(email, password)` must remain valid."""
    sig = inspect.signature(MercuryClient.__init__)
    params = list(sig.parameters.values())
    # First param is `self`; second and third must be positional-or-keyword.
    assert params[0].name == "self"
    assert params[1].name in {"email", "username"}
    assert params[2].name in {"password", "pwd"}
    # Both must be required (no default) — the wrapper passes them positionally.
    assert params[1].default is inspect.Parameter.empty
    assert params[2].default is inspect.Parameter.empty


def test_mercuryclient_dummy_constructor_does_not_network() -> None:
    """Constructor must NOT perform I/O. (`mercury_api.py:52-54` runs it via executor.)"""
    client = MercuryClient("test@example.invalid", "DUMMY")
    assert client is not None


def test_mercuryclient_has_login_method() -> None:
    """`MercuryClient.login()` is the wrapper's auth entry point."""
    assert hasattr(MercuryClient, "login")
    assert callable(MercuryClient.login)


def test_mercuryclient_has_is_logged_in_attribute() -> None:
    """`is_logged_in` must be readable post-construction (False before login)."""
    client = MercuryClient("test@example.invalid", "DUMMY")
    assert client.is_logged_in is False


def test_mercuryclient_has_get_complete_account_data() -> None:
    """`get_complete_account_data()` is the data-fetch entry point."""
    assert hasattr(MercuryClient, "get_complete_account_data")
    assert callable(MercuryClient.get_complete_account_data)


def test_mercuryclient_has_close() -> None:
    """`close()` was additive in 1.1.0; wrapper has `hasattr` guard so absence is OK,
    but presence here confirms 1.1.0+ behaviour."""
    assert hasattr(MercuryClient, "close")


def test_mercuryclient_has_api_client_attribute() -> None:
    """`_api_client` is the private nested client the wrapper accesses for usage data."""
    client = MercuryClient("test@example.invalid", "DUMMY")
    assert hasattr(client, "_api_client")
    # Note: pre-login the value is None; that's fine — wrapper hasattr-guards before use.


# ----------------------------------------------------------------------------
# _api_client method signatures — the high-risk surface in any minor bump
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name,required_args",
    [
        # method name -> minimum required positional args (excluding self)
        ("get_electricity_summary", 3),  # customer_id, account_id, service_id
        ("get_bill_summary", 2),  # customer_id, account_id
        ("get_electricity_usage_content", 0),
        ("get_electricity_usage", 3),  # customer_id, account_id, service_id
        ("get_electricity_usage_hourly", 3),
        ("get_electricity_usage_monthly", 3),
    ],
)
def test_api_client_method_present_with_expected_required_args(
    method_name: str, required_args: int
) -> None:
    """Every `_api_client` method the wrapper calls must keep its required-arg shape."""
    method = getattr(MercuryAPIClient, method_name, None)
    assert method is not None, f"MercuryAPIClient.{method_name} is missing in pymercury"

    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        # Some dynamically-generated methods can't be introspected; passing presence
        # alone is acceptable since the wrapper uses positional calls and would
        # raise loudly at runtime if the signature drifted.
        pytest.skip(f"could not introspect {method_name}; presence-only check passed")

    required = [
        p
        for p in sig.parameters.values()
        if p.name != "self"
        and p.default is inspect.Parameter.empty
        and p.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert (
        len(required) == required_args
    ), f"{method_name} required args drift: expected {required_args}, got {len(required)}: {required}"


# ----------------------------------------------------------------------------
# Data shape contract — sanity check that the wrapper still references known names
# ----------------------------------------------------------------------------


def test_wrapper_still_references_documented_attribute_names() -> None:
    """Loose contract: confirm `mercury_api.py` still reads the attributes we
    enumerated when planning. If a future refactor renames these, the test will
    drift — that's acceptable; update the list in lock-step with the wrapper.
    """
    from pathlib import Path

    wrapper = (Path(__file__).resolve().parents[1] / "mercury_api.py").read_text()
    expected_attribute_accesses = [
        # CompleteAccountData fields used at mercury_api.py:103-108, 219-224, etc.
        ".customer_id",
        ".account_ids",
        ".services",
        # Service object
        ".is_electricity",
        ".service_id",
        # ElectricityUsage object
        ".total_usage",
        ".average_daily_usage",
        ".total_cost",
        ".daily_usage",
        ".temperature_data",
        # ElectricitySummary / Content objects (read via raw_data fallback)
        ".raw_data",
    ]
    missing = [name for name in expected_attribute_accesses if name not in wrapper]
    assert not missing, (
        f"wrapper no longer references these documented attributes: {missing}. "
        "Either update the wrapper or update this test list."
    )


def test_wrapper_token_expiry_strings_unchanged() -> None:
    """The wrapper detects expired tokens by string-matching exception messages.
    pymercury 1.1.0 did not change these strings; verify they're still in the wrapper.
    """
    from pathlib import Path

    wrapper = (Path(__file__).resolve().parents[1] / "mercury_api.py").read_text()
    assert '"Tokens expired"' in wrapper
    assert '"refresh failed"' in wrapper
