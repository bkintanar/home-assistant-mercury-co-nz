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

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.const import CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mercury_co_nz.config_flow import MercuryOptionsFlow
from custom_components.mercury_co_nz.const import (
    CONF_EMAIL,
    CONF_ICP,
    DOMAIN,
    ICP_SCOPED_SENSOR_TYPES,
    SENSOR_TYPES,
    STATISTICS_COST_SUFFIX,
    STATISTICS_ENERGY_SUFFIX,
)
from custom_components.mercury_co_nz.coordinator import MercuryDataUpdateCoordinator
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


# ----------------------------------------------------------------------------
# v2.1.0 (#30): pin a single ICP per HA instance
# ----------------------------------------------------------------------------


def _svc(service_id: str, group: str = "electricity", address: str | None = None):
    """Stand-in for pymercury's Service (service_id/address/is_electricity/is_gas)."""
    return SimpleNamespace(
        service_id=service_id,
        address=address,
        is_electricity=group == "electricity",
        is_gas=group == "gas",
    )


ICP_A = "0001263891UN390"
ICP_B = "0001263892UN391"


async def _discover(
    hass,
    services: list,
    *,
    options: dict | None = None,
    persisted_primary: str | None = None,
):
    """Build a coordinator over `services` and run first-cycle ICP discovery."""
    data = {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "hunter2"}
    if persisted_primary is not None:
        data["_primary_service_id"] = persisted_primary
    entry = MockConfigEntry(domain=DOMAIN, data=data, options=options or {})
    entry.add_to_hass(hass)

    coordinator = MercuryDataUpdateCoordinator(hass, entry, timedelta(minutes=5))
    coordinator.api._client = MagicMock()
    coordinator.api._client.get_complete_account_data = MagicMock(
        return_value=SimpleNamespace(services=services)
    )

    await coordinator._discover_icps_if_needed()
    # Discovery swallows exceptions and retries next cycle — make a broken
    # fixture fail loudly instead of masquerading as "no ICPs found".
    assert coordinator._discovered is True
    return coordinator, entry


async def test_pinned_icp_filters_discovery_to_one(hass) -> None:
    """Pinning an ICP makes it the only discovered electricity service, so
    sensor.py creates ICP-scoped entities for it alone."""
    coordinator, _ = await _discover(
        hass, [_svc(ICP_A), _svc(ICP_B)], options={CONF_ICP: ICP_B}
    )
    assert [s.service_id for s in coordinator._discovered_electricity_services] == [
        ICP_B
    ]


async def test_pinned_icp_becomes_primary(hass) -> None:
    """The pin must also take over `primary` — account-scoped weekly_*/monthly_*
    top-level keys are written from the primary ICP's slice, so this is what
    scopes the summary sensors and the charts they feed."""
    coordinator, _ = await _discover(
        hass, [_svc(ICP_A), _svc(ICP_B)], options={CONF_ICP: ICP_B}
    )
    assert coordinator._primary_service_id == ICP_B


async def test_pinned_icp_gets_the_only_electricity_importer(hass) -> None:
    """One importer for the pinned ICP, flagged primary (legacy statistic_id)."""
    coordinator, _ = await _discover(
        hass, [_svc(ICP_A), _svc(ICP_B)], options={CONF_ICP: ICP_B}
    )
    electricity = {
        sid for fuel, sid in coordinator._importers if fuel == "electricity"
    }
    assert electricity == {ICP_B}
    assert coordinator._importers[("electricity", ICP_B)]._is_primary is True


async def test_pin_is_not_persisted_to_entry_data(hass) -> None:
    """The pin lives in entry.options only. entry.data keeps the *discovery*
    primary, which is what makes clearing the pin exactly reversible."""
    _, entry = await _discover(
        hass, [_svc(ICP_A), _svc(ICP_B)], options={CONF_ICP: ICP_B}
    )
    assert entry.data["_primary_service_id"] == ICP_A


async def test_pinned_icp_absent_falls_back_to_all(hass, caplog) -> None:
    """A pin for an ICP no longer on the account warns and degrades to v2.0.0
    behavior rather than leaving the user with no entities."""
    coordinator, _ = await _discover(
        hass, [_svc(ICP_A), _svc(ICP_B)], options={CONF_ICP: "ICP_GONE"}
    )
    assert [s.service_id for s in coordinator._discovered_electricity_services] == [
        ICP_A,
        ICP_B,
    ]
    assert coordinator._primary_service_id == ICP_A
    assert "pinned ICP ICP_GONE not found" in caplog.text


async def test_no_pin_is_unchanged_v200_behavior(hass) -> None:
    """Option unset ⇒ all ICPs discovered, primary == services[0]."""
    coordinator, entry = await _discover(hass, [_svc(ICP_A), _svc(ICP_B)])
    assert [s.service_id for s in coordinator._discovered_electricity_services] == [
        ICP_A,
        ICP_B,
    ]
    assert coordinator._primary_service_id == ICP_A
    assert entry.data["_primary_service_id"] == ICP_A


async def test_clearing_pin_reverts_primary_to_discovery_primary(hass) -> None:
    """After un-pinning, a previously-pinned ICP must not linger as primary."""
    coordinator, _ = await _discover(
        hass, [_svc(ICP_A), _svc(ICP_B)], options={}, persisted_primary=ICP_A
    )
    assert coordinator._primary_service_id == ICP_A
    assert len(coordinator._discovered_electricity_services) == 2


async def test_persisted_primary_survives_service_reorder(hass) -> None:
    """v2.0.0 invariant kept: a persisted primary that is still on the account
    wins over services[0], so a Mercury ordering change can't silently move an
    existing user's Energy Dashboard series."""
    coordinator, _ = await _discover(
        hass, [_svc(ICP_B), _svc(ICP_A)], persisted_primary=ICP_A
    )
    assert coordinator._primary_service_id == ICP_A


async def test_gas_services_unaffected_by_electricity_pin(hass) -> None:
    """Scoping is electricity-only for this iteration."""
    coordinator, _ = await _discover(
        hass,
        [_svc(ICP_A), _svc(ICP_B), _svc("GAS_1", group="gas")],
        options={CONF_ICP: ICP_B},
    )
    assert [s.service_id for s in coordinator._discovered_gas_services] == ["GAS_1"]


# ----------------------------------------------------------------------------
# v2.1.0 (#30): options flow
# ----------------------------------------------------------------------------


def _options_flow(hass, entry) -> MercuryOptionsFlow:
    """OptionsFlow wired up the way HA does it (config_entry resolves from handler)."""
    flow = MercuryOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    return flow


async def _entry_with_coordinator(hass, services, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "hunter2"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator._discovered_electricity_services = services
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return entry


async def test_options_flow_lists_discovered_icps_with_addresses(hass) -> None:
    """Choices come from live discovery and are labelled by address — the whole
    point is picking 'the ICP at this address'."""
    entry = await _entry_with_coordinator(
        hass,
        [_svc(ICP_A, address="1 Queen St"), _svc(ICP_B, address="2 King St")],
    )
    result = await _options_flow(hass, entry).async_step_init()

    assert result["type"] == FlowResultType.FORM
    choices = result["data_schema"].schema[CONF_ICP].container
    assert set(choices) == {"", ICP_A, ICP_B}
    assert choices[ICP_B] == f"{ICP_B} — 2 King St"


async def test_options_flow_aborts_before_first_discovery(hass) -> None:
    """No ICP list yet ⇒ tell the user to wait rather than showing an empty picker."""
    entry = await _entry_with_coordinator(hass, [])
    result = await _options_flow(hass, entry).async_step_init()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "icps_not_discovered"


async def test_options_flow_stores_selection(hass) -> None:
    entry = await _entry_with_coordinator(hass, [_svc(ICP_A), _svc(ICP_B)])
    result = await _options_flow(hass, entry).async_step_init({CONF_ICP: ICP_B})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ICP: ICP_B}


async def test_options_flow_all_icps_clears_the_pin(hass) -> None:
    """The '' sentinel is normalised to None so the coordinator sees no pin."""
    entry = await _entry_with_coordinator(
        hass, [_svc(ICP_A), _svc(ICP_B)], options={CONF_ICP: ICP_B}
    )
    result = await _options_flow(hass, entry).async_step_init({CONF_ICP: ""})

    assert result["data"] == {CONF_ICP: None}


async def test_options_flow_defaults_to_all_when_pin_is_stale(hass) -> None:
    """A pin for a departed ICP must not blow up the form with an invalid default."""
    entry = await _entry_with_coordinator(
        hass, [_svc(ICP_A)], options={CONF_ICP: "ICP_GONE"}
    )
    result = await _options_flow(hass, entry).async_step_init()

    # The default lives on the vol.Optional marker, not on the vol.In validator.
    marker = next(k for k in result["data_schema"].schema if k == CONF_ICP)
    assert marker.default() == ""
