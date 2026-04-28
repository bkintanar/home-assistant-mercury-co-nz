# Investigation: State attributes exceed 16KB → unit warnings cascade

**Issue**: [#4](https://github.com/bkintanar/home-assistant-mercury-co-nz/issues/4) (long-standing since 2026-01-28; surfaced again post-v1.2.2 deploy with HA 2025.11+'s stricter recorder).
**Type**: BUG
**Investigated**: 2026-04-27

### Assessment

| Metric     | Value     | Reasoning                                                                                                                                                                                |
| ---------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Severity   | **HIGH**  | Affects 3 chart sensors today (`energy_usage`, `total_usage`, `current_bill`); HA drops their attributes, suppresses long-term statistics, and the entity unit appears as `None` to consumers (incl. the recorder unit-conversion path). Database performance degraded. |
| Complexity | LOW       | Single-file change (`sensor.py`); strip unused `temperature_history`; truncate the chart-history lists to fit the 16KB budget. No frontend changes required.                                |
| Confidence | **HIGH**  | The user's exact log lines pinpoint both effects (`db_schema.py:582` + `sensor/recorder.py:368/639`). Root cause: HA recorder caps `state_attributes` at 16384 bytes; oversized attributes are dropped → unit not stored → statistics-compile fails unit-mismatch check. |

---

## Problem Statement

After v1.2.2 deploy, the user sees 9 log warnings on the next coordinator cycle:

1. **6× `db_schema.py:582`** — "State attributes for `sensor.mercury_nz_{total_usage,energy_usage,current_bill}_*` exceed maximum size of 16384 bytes. Attributes will not be stored."
2. **2× `recorder.py:368`** + **1× `recorder.py:639`** — "The unit of `sensor.mercury_nz_*` (None) cannot be converted to the unit of previously compiled statistics (kWh / $)."

The two error groups are **causally linked**: HA's recorder drops oversized attributes → `unit_of_measurement` isn't persisted → the sensor.recorder statistics-compile path reads NULL attributes and sees a unit-less state → it compares against historical statistics (which have unit kWh / $) and complains. **One fix resolves both.**

This is GitHub issue [#4](https://github.com/bkintanar/home-assistant-mercury-co-nz/issues/4), opened 2026-01-28 (~3 months ago) but never resolved. The v1.2.0 / v1.2.1 / v1.2.2 work indirectly increased pressure (the energy-dashboard statistics importer needs the full 180-day window in `coordinator.data`, although it doesn't read sensor attributes).

---

## Analysis

### 5 Whys

**WHY 1**: Why does the user see "State attributes exceed 16384 bytes"?
→ Because `sensor.py:233-329` (the `extra_state_attributes` property) returns a dict containing `daily_usage_history` (180 days × ~120 bytes = ~22KB), `temperature_history` (~9KB), `hourly_usage_history` (168 hours × ~100 bytes = ~17KB), `monthly_usage_history` (~1KB), `recent_temperatures` (~9KB) when `self._sensor_type` is in `CHART_DATA_SENSORS`.
Evidence: `sensor.py:240-246` defines `CHART_DATA_SENSORS = ["energy_usage", "total_usage", "current_bill"]`. Lines 248-329 unconditionally add 5+ history lists totaling well over 16KB.

**WHY 2**: Why does the unit warning fire?
→ Because HA's recorder, when it sees the oversized attributes, **drops them** rather than truncates. The `unit_of_measurement` attribute (which sensor.py sets via `_attr_native_unit_of_measurement = "kWh"` etc.) goes into the dropped attributes set. When sensor.recorder tries to compile long-term statistics, it reads the persisted state and finds no unit. It then compares against the previously-compiled stats (which have unit kWh) and emits the `recorder.py:368` warning.
Evidence: HA core `homeassistant/components/recorder/db_schema.py:582` warning mechanism (`SHARED_ATTRS_SCHEMA_LENGTH_LIMIT = 16384`); `homeassistant/components/sensor/recorder.py:368/639` unit-mismatch path.

**WHY 3**: Why is the `extra_state_attributes` so large?
→ Because v1.0.x of the integration deliberately attached the chart's full historical data to ENTITY ATTRIBUTES so the LitElement card can read `entity.attributes.daily_usage_history` to render. This worked when daily history was 7-30 days; it breaks now that the integration retains 180 days of daily + 7 days of hourly + multi-year monthly.
Evidence: `energy-usage-card.js:1043-1212` reads chart data via `entity.attributes.daily_usage_history` / `hourly_usage_history` / `monthly_usage_history` / `recent_temperatures`. `sensor.py:252-329` populates those attributes from `coordinator.data` without size guards.

**WHY 4**: Why hasn't anyone fixed this in the 3 months since issue #4 was filed?
→ Because the fix requires balancing UX (chart needs history) against the 16KB budget. The naive fix (drop history from attributes) breaks the card. The proper fix (move history to a JSON HTTP endpoint that the card fetches separately) is a moderate refactor of the card's data path.
Evidence: issue #4 has 1 comment from the maintainer asking for context but no PR linked. The deferred-effort tradeoff explains the gap.

### ROOT CAUSE

`sensor.py:233-329` (`extra_state_attributes`) attaches **all available** chart history to the 3 chart sensors with no size budget. Total size of attached attributes for a healthy multi-month installation is ~50-60KB — over 3× the recorder's 16KB cap.

### Affected Files

| File                                             | Lines     | Action | Description                                                                            |
| ------------------------------------------------ | --------- | ------ | -------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/sensor.py`      | 233-329   | UPDATE | Drop unused `temperature_history`; truncate `daily_usage_history`, `hourly_usage_history`, `recent_temperatures` to fit a configurable 14KB safety budget. |
| `custom_components/mercury_co_nz/const.py`       | append    | UPDATE | Add `CHART_ATTRIBUTE_DAILY_DAYS = 45`, `CHART_ATTRIBUTE_HOURLY_HOURS = 48` constants. |
| `custom_components/mercury_co_nz/manifest.json`  | version   | UPDATE | 1.2.2 → 1.2.3                                                                           |
| `custom_components/mercury_co_nz/tests/test_attributes.py` | NEW       | CREATE | Test that `extra_state_attributes` for each `CHART_DATA_SENSORS` entry stays under 16KB given a fixture with 180 days × 168 hours of synthetic data. |

### Integration Points

- `custom_components/mercury_co_nz/coordinator.py` populates `coordinator.data["extended_daily_usage_history"]` etc. — UNCHANGED. The full 180-day data stays in coordinator memory + JSON files for the statistics importer.
- `custom_components/mercury_co_nz/statistics.py` reads `coordinator.data["extended_daily_usage_history"]` directly (NOT entity attributes). UNCHANGED — Energy Dashboard backfill still works against the full 180-day window.
- `custom_components/mercury_co_nz/energy-usage-card.js:1043-1212` reads `entity.attributes.daily_usage_history`. After fix: receives 45 days instead of 180. Card pagination shows fewer pages (5 vs 15 at default 12-day pagination); navigation past 45 days falls off the end.
- `custom_components/mercury_co_nz/www/mercury_daily.json` — UNCHANGED. Full 180-day history is still persisted to disk and accessible via `/local/mercury_daily.json` if a future card refactor wants to restore the full range.

### Git History

- **Introduced**: `0c5a8b7` (LitElement refactor) and earlier commits that moved chart data to entity attributes. The bloat existed before v1.0.0; v1.1.0/v1.2.x added the 180-day extended history that pushed it over the cap.
- **Issue #4 opened**: 2026-01-28 by user reporting the warning.
- **No fix shipped yet**: 3 months of accumulated user pain. Fix this and close #4.
- **Implication**: original-bug, latent for ~3 months, surfaced louder now with v1.2.2's deploy (HA 2025.11+ recorder is stricter about logging this).

---

## Implementation Plan

### Step 1: Add chart-attribute size constants to const.py

**File**: `custom_components/mercury_co_nz/const.py`
**Action**: APPEND at the bottom (after existing `STATISTICS_*` constants).

**Required code**:

```python
# Chart attribute size limits (issue #4)
# HA recorder caps state_attributes at 16384 bytes; oversize attrs are DROPPED
# (not truncated), causing unit_of_measurement to be lost and downstream
# statistics-compile to fail unit-mismatch checks. We truncate the chart-history
# attributes in extra_state_attributes to stay comfortably under 14KB total.
#
# Full 180-day history is still retained in coordinator.data + the JSON files
# at www/mercury_daily.json — used by the statistics importer (Energy Dashboard
# gets 180-day backfill) and accessible via /local/ if a future card refactor
# wants to restore the full chart range without growing entity attributes.
CHART_ATTRIBUTE_DAILY_DAYS: Final[int] = 45
CHART_ATTRIBUTE_HOURLY_HOURS: Final[int] = 48
```

**Why**: Tunable constants (not magic numbers); future maintainers can adjust the budget without re-deriving the size math.

---

### Step 2: Update `extra_state_attributes` in sensor.py to truncate

**File**: `custom_components/mercury_co_nz/sensor.py`
**Lines**: 233-356 area
**Action**: UPDATE — three substantive changes:

  1. Drop `temperature_history` exposure entirely (unused by the card; verified by grep — card uses `recent_temperatures` only).
  2. Truncate `daily_usage_history` and `recent_temperatures` to last `CHART_ATTRIBUTE_DAILY_DAYS` entries.
  3. Truncate `hourly_usage_history` to last `CHART_ATTRIBUTE_HOURLY_HOURS` entries.

**Current code** (representative; see `sensor.py:252-329` for full block):

```python
if "extended_daily_usage_history" in self.coordinator.data:
    daily_history = self.coordinator.data["extended_daily_usage_history"]
    attributes["data_source"] = "mercury_energy_api_extended"
    ...
elif "daily_usage_history" in self.coordinator.data:
    daily_history = self.coordinator.data["daily_usage_history"]
    ...

if "daily_usage_history" in self.coordinator.data or "extended_daily_usage_history" in self.coordinator.data:
    attributes["daily_usage_history"] = daily_history
```

**Required change**:

```python
from .const import CHART_ATTRIBUTE_DAILY_DAYS, CHART_ATTRIBUTE_HOURLY_HOURS  # add to top imports

# Daily usage history — truncate to fit attribute size budget (issue #4)
daily_source = (
    self.coordinator.data.get("extended_daily_usage_history")
    or self.coordinator.data.get("daily_usage_history")
)
if daily_source:
    if "extended_daily_usage_history" in self.coordinator.data:
        attributes["data_source"] = "mercury_energy_api_extended"
    else:
        attributes["data_source"] = "mercury_energy_api"
    # Last N days (the card paginates 12 days by default; 45 days = ~4 pages)
    # Full 180-day history stays in coordinator.data for the statistics importer.
    attributes["daily_usage_history"] = daily_source[-CHART_ATTRIBUTE_DAILY_DAYS:]
```

Replace the temperature block (lines 281-298) with:

```python
# Temperature history — truncate `recent_temperatures` only.
# Drop `temperature_history` attribute (unused by the card; verified by grep —
# the card reads `recent_temperatures` only).
temp_source = (
    self.coordinator.data.get("extended_temperature_history")
    or self.coordinator.data.get("temperature_history")
)
if temp_source:
    truncated_temps = temp_source[-CHART_ATTRIBUTE_DAILY_DAYS:]
    attributes["recent_temperatures"] = [
        {
            "date": day.get("date", "").split("T")[0],
            "temperature": day.get("temp", 0),
        }
        for day in truncated_temps
    ]
```

Replace the hourly block (lines 300-319) with:

```python
# Hourly usage history — truncate to ~last 2 days
hourly_source = (
    self.coordinator.data.get("extended_hourly_usage_history")
    or self.coordinator.data.get("hourly_usage_history")
)
if hourly_source:
    if "extended_hourly_usage_history" in self.coordinator.data:
        attributes["data_source_hourly"] = "mercury_energy_api_extended"
    else:
        attributes["data_source_hourly"] = "mercury_energy_api"
    attributes["hourly_usage_history"] = hourly_source[-CHART_ATTRIBUTE_HOURLY_HOURS:]
```

The `monthly_usage_history` block (lines 321-329) is small (~1KB total) — leave unchanged.

**Why**: Each truncation is a one-line change that preserves the card's existing data path (it still reads `entity.attributes.{daily,hourly,monthly}_usage_history` and `recent_temperatures`); the card's pagination just shows fewer pages.

---

### Step 3: Bump manifest

**File**: `custom_components/mercury_co_nz/manifest.json`
**Action**: UPDATE — version `1.2.2` → `1.2.3`.

---

### Step 4: Add attribute-size tests

**File**: `custom_components/mercury_co_nz/tests/test_attributes.py`
**Action**: CREATE.

**Test cases**:

```python
"""Test that extra_state_attributes stays under HA's 16KB cap (issue #4)."""

# pylint: disable=protected-access
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.mercury_co_nz.const import (
    CHART_ATTRIBUTE_DAILY_DAYS,
    CHART_ATTRIBUTE_HOURLY_HOURS,
    DEFAULT_NAME,
    SENSOR_TYPES,
)
from custom_components.mercury_co_nz.sensor import MercurySensor

# HA recorder cap from homeassistant/components/recorder/db_schema.py:
# SHARED_ATTRS_SCHEMA_LENGTH_LIMIT = 16384.
RECORDER_ATTRS_LIMIT = 16384

# Generous safety margin — leave 2KB headroom for HA's own json overhead.
SAFETY_BUDGET = 14000


def _coordinator_with_synthetic_data():
    """Build a coordinator stub with 180 days daily + 168 hours hourly + 24 months."""
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
        f"{sensor_type} attributes are {len(serialized)} bytes; cap is {RECORDER_ATTRS_LIMIT}"
    )


@pytest.mark.parametrize("sensor_type", ["energy_usage", "total_usage", "current_bill"])
def test_chart_sensor_attributes_under_safety_budget(sensor_type: str) -> None:
    """Stay comfortably under the cap to absorb future field additions."""
    sensor = _make_sensor(sensor_type)
    serialized = json.dumps(sensor.extra_state_attributes)
    assert len(serialized) < SAFETY_BUDGET, (
        f"{sensor_type} attributes are {len(serialized)} bytes; safety budget is {SAFETY_BUDGET}"
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
    for key in ("daily_usage_history", "hourly_usage_history", "monthly_usage_history",
                "recent_temperatures", "temperature_history"):
        assert key not in attrs, f"non-chart sensor leaked {key} attribute"


def test_data_source_marker_preserved() -> None:
    """The `data_source` marker still reflects extended-vs-not (sanity check)."""
    sensor = _make_sensor("energy_usage")
    assert sensor.extra_state_attributes["data_source"] == "mercury_energy_api_extended"
```

**Why**: Locks in the 16KB invariant. If a future change re-adds `temperature_history` or expands the truncation windows, these tests catch it before users do.

---

## Patterns to Follow

The existing pattern at `sensor.py:252-262` (use `extended_daily_usage_history` if present, fall back to `daily_usage_history`) is preserved — the truncation is a final `[-N:]` slice, leaving the rest of the data-source-selection logic untouched.

Test fixture style mirrors `tests/test_statistics.py` and `tests/test_plans.py` — pure-helper / dict-based mocks, no `hass` fixture required.

---

## Edge Cases & Risks

| Risk / Edge Case                                                                              | Mitigation                                                                                                                            |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Card pagination expects 180 days; user navigates past day 45 → no data                        | Last `CHART_ATTRIBUTE_DAILY_DAYS=45` days = 3.75 pages of 12-day default. Beyond that the card's "no more data" UX kicks in (already exists per existing pagination logic). |
| User has < 45 days of history (fresh install)                                                 | Slice `[-45:]` returns all available entries when `len(source) < 45`. No-op for fresh installs.                                       |
| Truncation drops the most-RECENT or most-OLDEST entries by mistake                            | Unit test `test_daily_usage_history_truncated_to_chart_window` verifies length; ordering is preserved by `[-N:]`.                     |
| Another developer re-adds `temperature_history` for some reason                               | `test_temperature_history_no_longer_exposed` blocks regression.                                                                       |
| Future fields added to the chart attributes that push back over 16KB                          | `test_chart_sensor_attributes_under_safety_budget` (14KB safety margin) catches it before `test_chart_sensor_attributes_under_16kb` does. |
| HA increases the 16KB cap in a future release                                                 | Test `RECORDER_ATTRS_LIMIT` constant is local to the test file — easy to update if HA bumps the cap. We're at 14KB, well under.       |
| Existing user's recorder still has the old over-cap entries cached                            | After 1.2.3 deploys, the next coordinator update writes properly-sized attributes; HA doesn't retroactively re-validate old rows. The unit-mismatch warning resolves on the first new state-write that includes the unit. No manual user action required. |
| `bill_statement_details` is also added unconditionally to all sensors at line 334-335         | Out of scope. Typically small (12 entries × ~80 bytes). Tests cover the realistic chart sensor; if `bill_statement_details` ever bloats, the `test_chart_sensor_attributes_under_safety_budget` test catches it (it includes that attribute). |

---

## Validation

### Automated

```bash
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/
.venv/bin/python -m black --check custom_components/mercury_co_nz/tests/test_attributes.py
.venv/bin/python -m mypy --ignore-missing-imports --follow-imports=silent --explicit-package-bases custom_components/mercury_co_nz/tests/test_attributes.py
```

**EXPECT**: 56 (existing 1.2.2) + ~8 (new 1.2.3) = 64+ tests pass. Specifically the 3 parameterized size tests pass (one per chart sensor type).

### Manual

1. Deploy 1.2.3 via `./deploy.sh` + HA restart.
2. Wait one coordinator cycle (~5 min).
3. Settings → System → Logs. Confirm:
   - **No more** `db_schema.py:582` "State attributes exceed maximum size of 16384 bytes" warnings.
   - **No more** `recorder.py:368/639` "unit cannot be converted" warnings.
4. Energy Dashboard / chart card UX check:
   - Daily view shows last ~45 days (instead of 180). Pagination forward shows "no more data" past day 45.
   - Hourly view shows last 48 hours.
   - Monthly view unchanged.
5. Energy Dashboard backfill (from PR #7) is unaffected — `developer_tools/statistics` should still show 180 days of `mercury_co_nz:*_energy_consumption` series.

---

## Scope Boundaries

**IN SCOPE:**

- Truncate `daily_usage_history`, `recent_temperatures`, `hourly_usage_history` in `extra_state_attributes`.
- Drop unused `temperature_history` exposure.
- Configurable constants in `const.py`.
- Tests covering the 16KB invariant + truncation correctness + non-chart-sensor isolation.

**OUT OF SCOPE:**

- **Move chart history to JSON HTTP fetch** — the proper long-term fix where the card reads `/local/mercury_daily.json` directly via `fetch()`. Restores full 180-day card history without growing entity attributes. Deferred to a v1.3.0 card refactor (separate PRP plan).
- **Statistics importer changes** — unaffected; reads `coordinator.data` directly, not entity attributes.
- **`bill_statement_details` attribute** — leave as-is. The test catches if it ever bloats.
- **Unit-warning resolution itself** — happens automatically as a side effect of attribute-size fix. No code change needed for it specifically.
- **Issue #5 (multi-ICP)** — separate plan exists at `.claude/PRPs/plans/multi-icp-support.plan.md`; out of scope here.
- **`v1.2.1` diagnostic logging removal** — defer to a v1.2.4 cleanup once we're confident plan_* sensors are stable.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-27
- **Artifact**: `.claude/PRPs/issues/issue-4-attribute-size-overflow.md`
- **Closes**: GitHub issue #4 (long-standing 3 months).
- **Related**: PR #7 (statistics importer; uses `coordinator.data` directly so unaffected by the attribute truncation), PR #10 (v1.2.2 plan-rate fix; merged but unrelated to this).
