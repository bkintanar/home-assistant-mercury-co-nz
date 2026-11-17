"""Network suggestions stay editable and isolated to the selected meter."""

from datetime import datetime
import hashlib
from types import SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mercury_co_nz.config_flow import MercuryOptionsFlow
from custom_components.mercury_co_nz.network_tariffs import NETWORK_TARIFFS
from custom_components.mercury_co_nz.tariff import (
    Schedule,
    build_breakdown,
    normalize_hours,
)
from .test_tariffs import OPTIONS, day_records


def make_flow(hass, options=None):
    entry = MockConfigEntry(domain="mercury_co_nz", data={}, options=options or {})
    entry.add_to_hass(hass)
    hass.data.setdefault("mercury_co_nz", {})[entry.entry_id] = SimpleNamespace(
        _all_electricity_services=[SimpleNamespace(service_id="home", address="Home")]
    )
    flow = MercuryOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    return entry, flow


async def test_preset_prefills_then_saves_user_override(hass):
    entry, flow = make_flow(hass, {"tariff_schedules": {"other": OPTIONS}})
    await flow.async_step_tariff_meter()
    form = await flow.async_step_tariff_network({"network_tariff": "orion"})
    fields = form["data_schema"]({})
    assert fields["night_start"] == "21:00"
    assert fields["night_end"] == "07:00"
    assert fields["enabled"] is False
    assert fields["weekend_night"] is False
    assert (
        NETWORK_TARIFFS["orion"].source
        in form["description_placeholders"]["suggestion"]
    )
    fields.update(enabled=True, night_start="22:00", time_zone="Etc/GMT-12")
    result = await flow.async_step_tariff(fields)
    saved = result["data"]["tariff_schedules"]
    assert saved["home"]["night_start"] == "22:00"
    assert saved["other"] == OPTIONS
    hass.config_entries.async_update_entry(entry, options=result["data"])

    # Opening settings must not replace a saved override with catalogue hours.
    await flow.async_step_tariff_meter()
    form = await flow.async_step_tariff_network({"network_tariff": "manual"})
    assert form["data_schema"]({}) == fields
    assert Schedule.from_options(saved["home"]).key == Schedule.from_options(fields).key


async def test_switching_to_manual_network_clears_previous_preset(hass):
    entry, flow = make_flow(
        hass,
        {
            "tariff_schedules": {
                "home": {
                    **OPTIONS,
                    "network_tariff": "orion_weekend",
                    "weekend_night": True,
                }
            }
        },
    )
    await flow.async_step_tariff_meter()
    form = await flow.async_step_tariff_network({"network_tariff": "wel"})
    defaults = form["data_schema"]({})
    assert defaults["enabled"] is False
    assert defaults["weekend_night"] is False
    assert "night_start" not in defaults
    assert "night_end" not in defaults
    invalid = await flow.async_step_tariff({**defaults, "enabled": True})
    assert invalid["errors"]["base"] == "invalid_tariff_schedule"
    # Selecting and abandoning a preset never mutates saved options.
    assert entry.options["tariff_schedules"]["home"]["night_start"] == "21:00"
    result = await flow.async_step_tariff(
        {
            **defaults,
            "enabled": True,
            "night_start": "22:00",
            "night_end": "08:00",
        }
    )
    assert result["data"]["tariff_schedules"]["home"]["night_end"] == "08:00"


async def test_weekend_preset_can_be_edited_and_validation_keeps_values(hass):
    _, flow = make_flow(hass)
    await flow.async_step_tariff_meter()
    invalid = await flow.async_step_tariff_network({"network_tariff": "missing"})
    assert invalid["errors"] == {"base": "invalid_network"}
    form = await flow.async_step_tariff_network({"network_tariff": "orion_weekend"})
    fields = form["data_schema"]({})
    assert fields["weekend_night"] is True
    invalid = await flow.async_step_tariff(
        {
            **fields,
            "enabled": True,
            "night_start": "20:00",
            "start_date": "invalid",
        }
    )
    assert invalid["errors"]
    assert invalid["data_schema"]({})["night_start"] == "20:00"
    result = await flow.async_step_tariff(
        {"start_date": "2026-01-01", "weekend_night": False}
    )
    assert result["data"]["tariff_schedules"]["home"]["weekend_night"] is False
    assert result["data"]["tariff_schedules"]["home"]["night_start"] == "20:00"


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2026-11-13T20:00:00+13:00", "day"),
        ("2026-11-13T21:00:00+13:00", "night"),
        ("2026-11-14T12:00:00+13:00", "night"),
        ("2026-11-15T23:00:00+13:00", "night"),
        ("2026-11-16T06:00:00+13:00", "night"),
        ("2026-11-16T07:00:00+13:00", "day"),
    ],
)
def test_weekend_boundaries(stamp, expected):
    schedule = Schedule.from_options({**OPTIONS, "weekend_night": True})
    assert schedule.period(datetime.fromisoformat(stamp)) == expected


@pytest.mark.parametrize(("day", "hours"), [("2026-04-05", 25), ("2026-09-27", 23)])
def test_weekend_statistics_include_both_dst_transitions(day, hours):
    schedule = Schedule.from_options({**OPTIONS, "weekend_night": True})
    series = build_breakdown(normalize_hours(day_records(day)), schedule)
    assert series["night"][-1]["sum"] == hours
    assert series["day"][-1]["sum"] == 0


def test_weekend_uses_selected_timezone_and_preserves_existing_series():
    daily = Schedule.from_options(OPTIONS)
    old_key = hashlib.sha256(b"21:7:2026-01-01:Pacific/Auckland").hexdigest()[:12]
    assert daily.key == old_key
    assert Schedule.from_options({**OPTIONS, "weekend_night": False}).key == old_key
    weekend = Schedule.from_options({**OPTIONS, "weekend_night": True})
    assert weekend.key != old_key
    fixed = Schedule.from_options(
        {**OPTIONS, "weekend_night": True, "time_zone": "Etc/GMT-12"}
    )
    stamp = datetime.fromisoformat("2026-11-16T07:00:00+13:00")
    assert weekend.period(stamp) == "day"
    assert fixed.period(stamp) == "night"
    future = Schedule.from_options(
        {**OPTIONS, "weekend_night": True, "start_date": "2027-01-01"}
    )
    assert future.period(stamp) is None


def test_catalogue_defaults_are_valid_and_never_enabled():
    for preset in NETWORK_TARIFFS.values():
        assert preset.source.startswith("https://")
        if not preset.defaults:
            assert preset.night_end is None
            continue
        assert "enabled" not in preset.defaults
        Schedule.from_options({**OPTIONS, **preset.defaults})
