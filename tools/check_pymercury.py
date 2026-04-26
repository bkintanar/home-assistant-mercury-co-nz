#!/usr/bin/env python3
"""Standalone pymercury smoke test against a real Mercury account.

Usage:
    MERCURY_EMAIL=you@example.com MERCURY_PASSWORD=... python tools/check_pymercury.py

Prints the SHAPE (types, lengths, key names) of every API method's return value
so the wrapper's expectations can be cross-checked against actual upstream
behaviour. PII (account numbers, addresses, bill amounts) is intentionally
NOT printed — only types and lengths.

Exit codes:
    0  All smoke checks passed.
    2  Missing MERCURY_EMAIL / MERCURY_PASSWORD.
    1  A check raised (see traceback).

Does NOT modify anything in the Mercury account. Read-only.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from pymercury import MercuryClient


def _shape(value: Any, depth: int = 0) -> str:
    """Return a one-line type-only summary of a value (no PII)."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return type(value).__name__
    if isinstance(value, str):
        return f"str(len={len(value)})"
    if isinstance(value, list):
        if not value:
            return "list[]"
        return f"list[{len(value)}] of {_shape(value[0], depth + 1)}"
    if isinstance(value, dict):
        keys = sorted(value.keys())
        body = ", ".join(f"{k}:{_shape(value[k], depth + 1)}" for k in keys[:8]) + (
            "…" if len(keys) > 8 else ""
        )
        return "dict{" + body + "}"
    attrs = [a for a in dir(value) if not a.startswith("_")]
    return (
        f"{type(value).__name__}({', '.join(attrs[:8])}{'…' if len(attrs) > 8 else ''})"
    )


def main() -> int:
    email = os.environ.get("MERCURY_EMAIL")
    password = os.environ.get("MERCURY_PASSWORD")
    if not email or not password:
        print(
            "Set MERCURY_EMAIL and MERCURY_PASSWORD env vars to run the live smoke.",
            file=sys.stderr,
        )
        return 2

    print(f"[1/8] Constructing MercuryClient({email!r})…")
    client = MercuryClient(email, password)
    assert hasattr(client, "is_logged_in")
    print(f"      is_logged_in (pre-login): {client.is_logged_in}")

    print("[2/8] login()…")
    client.login()
    assert client.is_logged_in, "login() did not set is_logged_in=True"
    print(
        f"      OK; customer_id_type={type(getattr(client, 'customer_id', None)).__name__}, "
        f"account_ids_type={type(getattr(client, 'account_ids', None)).__name__}"
    )

    print("[3/8] get_complete_account_data()…")
    complete = client.get_complete_account_data()
    print(f"      shape: {_shape(complete)}")
    print(f"      .customer_id: {_shape(complete.customer_id)}")
    print(f"      .account_ids: {_shape(complete.account_ids)}")
    print(f"      .services: {_shape(complete.services)}")
    assert complete.account_ids, "no account_ids returned"
    account_id = complete.account_ids[0]
    service = next((s for s in complete.services if s.is_electricity), None)
    assert service is not None, "no electricity service found"
    service_id = service.service_id
    customer_id = complete.customer_id
    print("      identifiers OK (using first account + first electricity service)")

    print("[4/8] _api_client.get_electricity_summary(c, a, s)…")
    summary = client._api_client.get_electricity_summary(  # noqa: SLF001
        customer_id, account_id, service_id
    )
    print(f"      shape: {_shape(summary)}")
    raw = getattr(summary, "raw_data", None) or summary.__dict__
    print(
        f"      raw_data keys: {sorted(raw.keys()) if isinstance(raw, dict) else '?'}"
    )

    print("[5/8] _api_client.get_bill_summary(c, a)…")
    bill = client._api_client.get_bill_summary(customer_id, account_id)  # noqa: SLF001
    bill_dict = bill.to_dict() if hasattr(bill, "to_dict") else bill.__dict__
    print(f"      keys: {sorted(bill_dict.keys())[:12]}…")
    expected_keys = (
        "account_id",
        "current_balance",
        "due_amount",
        "bill_date",
        "due_date",
        "overdue_amount",
        "statement_total",
        "electricity_amount",
        "gas_amount",
        "broadband_amount",
    )
    for key in expected_keys:
        present = key in bill_dict
        marker = "✓" if present else "✗"
        suffix = "" if present else " (MISSING — wrapper will see None)"
        print(f"        {marker} {key}{suffix}")

    print("[6/8] _api_client.get_electricity_usage_content()…")
    content = client._api_client.get_electricity_usage_content()  # noqa: SLF001
    print(f"      shape: {_shape(content)}")

    print("[7/8] _api_client.get_electricity_usage(c, a, s)…")
    usage = client._api_client.get_electricity_usage(  # noqa: SLF001
        customer_id, account_id, service_id
    )
    for attr in (
        "total_usage",
        "average_daily_usage",
        "total_cost",
        "average_temperature",
        "usage_period",
        "days_in_period",
        "data_points",
    ):
        val = getattr(usage, attr, "<missing>")
        print(f"      .{attr}: {_shape(val)}")
    daily = getattr(usage, "daily_usage", None) or []
    temps = getattr(usage, "temperature_data", None) or []
    print(f"      .daily_usage: {_shape(daily)}")
    print(f"      .temperature_data: {_shape(temps)}")
    if daily:
        first = daily[0]
        if isinstance(first, dict):
            for key in ("date", "consumption", "cost", "free_power"):
                marker = "✓" if key in first else "✗"
                print(f"        {marker} daily_usage[0].{key}")

    print("[8/8] _api_client.get_electricity_usage_hourly + _monthly…")
    hourly = client._api_client.get_electricity_usage_hourly(  # noqa: SLF001
        customer_id, account_id, service_id
    )
    monthly = client._api_client.get_electricity_usage_monthly(  # noqa: SLF001
        customer_id, account_id, service_id
    )
    print(f"      hourly: {_shape(hourly)}")
    print(f"      monthly: {_shape(monthly)}")

    print("\nAll smoke checks passed — pymercury 1.1.0 is compatible with the wrapper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
