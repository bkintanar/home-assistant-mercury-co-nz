# Investigation: Stale unit-mix warnings post-v1.2.3 (transient + latent state_class bug)

**Issue**: continuation of [#4](https://github.com/bkintanar/coopnz/home-assistant-mercury-co-nz/issues/4) — surfaced after v1.2.3 deploy at 06:40:10 NZ time.
**Type**: BUG (mostly transient cleanup + 1 latent code issue)
**Investigated**: 2026-04-27

### Assessment

| Metric     | Value     | Reasoning                                                                                                                                                            |
| ---------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Severity   | **MEDIUM**  | Warnings are noisy but not data-loss. Long-term statistics for 3 entity-level sensors are suppressed until cleared. Energy Dashboard (which uses external statistics from PR #7) is unaffected. |
| Complexity | LOW       | Primary fix is **a one-time user action** in HA's UI (Developer Tools → Statistics → Fix Issue). Optional code hardening for the latent state_class bug is a 3-line `const.py` change. |
| Confidence | **HIGH**  | The unit-mix warning's mechanism is well-documented in HA core. v1.2.3's attribute fix (PR #11) correctly resolved the *upstream* cause; the warnings are HA's recorder correctly noticing the stale pre-v1.2.3 state history. |

---

## Problem Statement

After v1.2.3 (PR #11) deployed and resolved the `db_schema.py:582` 16KB attribute warnings, the user is **still** seeing 3 unit-related warnings on the next coordinator cycle:

1. `recorder.py:335` — `sensor.mercury_nz_current_bill_7_days` "is changing, got multiple `{None, '$'}`"
2. `recorder.py:368` — `sensor.mercury_nz_total_usage_7_days` "(None) cannot be converted to (kWh)"
3. `recorder.py:368` — `sensor.mercury_nz_energy_usage` "(None) cannot be converted to (kWh)"

**v1.2.3's attribute fix is working correctly.** The 3 warnings come from HA's recorder reading state rows that were written BEFORE v1.2.3 deployed — back when the oversized attributes were being dropped, taking `unit_of_measurement` with them. Those stale `unit=None` rows are still in HA's recorder DB; they age out at the default 10-day retention OR can be purged immediately via HA's Developer Tools → Statistics UI.

There's also a separate **latent** bug surfaced by these warnings: `total_usage`, `hourly_usage`, `monthly_usage` are tagged `state_class=total_increasing` but their values are windowed sums that decrease when the API window rolls. This was flagged in PR #7's investigation as "out of scope" but is now contributing to the noise.

---

## Analysis

### The "still seeing warnings" mystery — explained

After v1.2.3 deploy:
1. **NEW state writes** (post-deploy) → attributes fit under 16KB → HA stores `unit_of_measurement` correctly. ✓
2. **OLD state writes** (pre-deploy, last ~10 days at HA's default recorder retention) → attributes were dropped → `unit_of_measurement` is `NULL` in the recorder DB.

When HA's `sensor/recorder.py` compiles statistics on the next cycle, it scans the entity's RECENT state history (typically the last 24h–10d). It sees a mix:
- Some rows with `unit='$'` (post-v1.2.3).
- Some rows with `unit=NULL` (pre-v1.2.3).

The `recorder.py:335` warning specifically flags this kind of mix: *"is changing, got multiple {None, '$'}"*.

For `total_usage_7_days` and `energy_usage`, the previously compiled statistics table has `unit=kWh`. The current state still has `unit=kWh` (post-v1.2.3) BUT the recorder is reading the recent history which includes the `unit=NULL` rows. It picks the most recent one (which might still be a None one from the deploy moment) and complains about converting `None → kWh`.

### Why this resolves with the standard HA UI fix

`https://my.home-assistant.io/redirect/developer_statistics` (the URL embedded in HA's warning) opens **Developer Tools → Statistics**. There the user can:
- Click "Fix Issue" next to each affected entity.
- Choose **"Yes, update the unit"** — HA accepts the new unit and re-aligns. **Recommended for this case**.
- OR "No, the statistic IDs are correct" — HA dismisses the warning without changing anything.

Choosing "Yes, update the unit" is the canonical fix when you've intentionally changed/restored a sensor's unit. It tells HA to discard the conflicting historical-stat record, accept the current unit (`kWh`/`$`), and start a fresh statistics compilation from now.

### Latent issue: `state_class=total_increasing` on windowed sums

Per `const.py:34-39`, `90-95`, `97-102`:

```python
"total_usage": {
    "name": "Total Usage (7 days)",
    "unit": "kWh",
    "device_class": "energy",
    "state_class": "total_increasing",   # ← BUG: value is a windowed sum, not monotonic
},
"hourly_usage": {
    "name": "Hourly Usage (7 days)",
    "unit": "kWh",
    "device_class": "energy",
    "state_class": "total_increasing",   # ← BUG
},
"monthly_usage": {
    "name": "Monthly Usage (2 months)",
    "unit": "kWh",
    "device_class": "energy",
    "state_class": "total_increasing",   # ← BUG
},
```

These sensors expose Mercury's WINDOWED-SUM totals (last 7 days, last 7 days hourly, last 2 months). When the window rolls, the value **decreases** (the oldest day drops out of the 7-day window). HA's `total_increasing` contract requires monotonic non-decreasing values; decreases trigger "unexpected dip" warnings AND can corrupt the `total_increasing` accumulator in the recorder.

PR #7's investigation flagged this as out-of-scope at the time. It's a **latent** bug that's been silently misreporting since v1.0.0.

### Affected Files

| File                                             | Lines                | Action | Description                                                                              |
| ------------------------------------------------ | -------------------- | ------ | ---------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/const.py`       | 39, 95, 102          | UPDATE | Change `state_class` from `"total_increasing"` to `"total"` (or `None`) for the 3 windowed-sum sensors. |
| `custom_components/mercury_co_nz/manifest.json`  | version              | UPDATE | 1.2.3 → 1.2.4                                                                             |
| `custom_components/mercury_co_nz/tests/test_state_class.py` | NEW          | CREATE | Test that windowed-sum sensors don't have `total_increasing` state_class. |
| `README.md`                                      | new section          | UPDATE | Add post-deploy troubleshooting note: "If you see unit warnings after upgrading to v1.2.3+, run Developer Tools → Statistics → Fix Issue → Yes, update the unit." |

### Integration Points

- HA core `sensor/recorder.py:335` and `:368` — the warning paths, unchanged. They're correctly reporting the stale state.
- HA Developer Tools → Statistics — the user-facing fix path; not modified by us.
- Statistics importer (PR #7) — UNAFFECTED. It writes EXTERNAL statistics under `mercury_co_nz:*` IDs; the entity-level statistics that have the unit-mix issue are SEPARATE.

### Git History

- **Issue first opened**: 2026-01-28 (issue #4 — symptom only).
- **Latent state_class bug introduced**: pre-v1.0.0 (these sensors have always been `total_increasing`).
- **PR #7 investigation flagged it**: 2026-04-26 — explicitly deferred as out-of-scope.
- **PR #11 (v1.2.3) attribute fix**: 2026-04-26 — addressed the upstream cause; user is now seeing the residue.

---

## Implementation Plan

### Step 1 (USER ACTION — primary fix): Clear stale statistics via HA UI

**This is the recommended immediate fix. No code change required.**

For each of the 3 sensors with the warning:

1. Open Home Assistant → **Developer Tools** → **Statistics** tab.
2. Find each of:
   - `sensor.mercury_nz_total_usage_7_days`
   - `sensor.mercury_nz_energy_usage`
   - `sensor.mercury_nz_current_bill_7_days`
3. Click **"Fix Issue"**.
4. Choose **"Update the unit"** (or "Yes, the statistic IDs are correct, but the unit changed").
5. Repeat for each entity.

The 3 warnings disappear immediately.

**Why this works**: HA's recorder maintains a per-entity "compiled statistics" lock that records the entity's expected unit. When the unit changes (in this case, restored from `None` to the proper value), HA refuses to silently re-align without user consent. The "Update the unit" button is that consent.

The Energy Dashboard's `mercury_co_nz:*_energy_consumption` and `mercury_co_nz:*_energy_cost` external statistics (added by PR #7) are NOT affected by this — they have a different statistic_id namespace.

---

### Step 2 (OPTIONAL CODE FIX — v1.2.4): Correct latent `state_class` on windowed-sum sensors

**File**: `custom_components/mercury_co_nz/const.py`
**Lines**: 39, 95, 102
**Action**: UPDATE

**Current code** (`const.py:34-40`):

```python
"total_usage": {
    "name": "Total Usage (7 days)",
    "unit": "kWh",
    "icon": "mdi:lightning-bolt",
    "device_class": "energy",
    "state_class": "total_increasing",   # WRONG — value is a windowed sum
},
```

**Required change**:

```python
"total_usage": {
    "name": "Total Usage (7 days)",
    "unit": "kWh",
    "icon": "mdi:lightning-bolt",
    "device_class": "energy",
    "state_class": "total",   # FIX: windowed sum, may decrease when window rolls
},
```

Same change for `hourly_usage` (line 95) and `monthly_usage` (line 102).

**Why `total` (not `measurement` or `None`)**:
- `total_increasing` requires monotonic non-decreasing → wrong for windowed sums.
- `total` allows up-and-down values; HA stores the running sum based on `last_reset` (which Mercury doesn't provide; HA falls back to first-seen value).
- `measurement` would lose the long-term-statistics integration entirely (since `measurement` doesn't get summed in long-term stats).
- `total` is the closest HA-canonical match for "Mercury reports a running window total".

This change preserves the entity's role in HA's energy/statistics dashboards but stops the contract violation that's been silent since v1.0.0.

### Step 3: Add `device_class=energy` invariant test

**File**: `custom_components/mercury_co_nz/tests/test_state_class.py` (NEW)

```python
"""Test invariants on SENSOR_TYPES state_class assignments (issue #4 follow-up)."""

# pylint: disable=protected-access
from __future__ import annotations

from custom_components.mercury_co_nz.const import SENSOR_TYPES


def test_windowed_sum_sensors_not_total_increasing() -> None:
    """Sensors that expose Mercury's windowed sums (which decrease when the
    window rolls) must NOT be tagged total_increasing — that contract requires
    monotonic non-decreasing values.
    """
    windowed_sum_sensors = ("total_usage", "hourly_usage", "monthly_usage")
    for sensor_type in windowed_sum_sensors:
        config = SENSOR_TYPES[sensor_type]
        assert config["state_class"] != "total_increasing", (
            f"{sensor_type} is a windowed sum (value decreases when window rolls); "
            f"state_class=total_increasing violates HA's monotonic contract."
        )


def test_state_class_present_for_numeric_sensors() -> None:
    """Sanity check: numeric sensors with kWh/$ units have a state_class."""
    for sensor_type, config in SENSOR_TYPES.items():
        unit = config.get("unit")
        if unit in ("kWh", "$", "NZD/kWh", "NZD/day"):
            assert config["state_class"] is not None, (
                f"{sensor_type} has unit {unit} but no state_class — "
                "long-term statistics will be skipped."
            )
```

### Step 4: Update README with troubleshooting note

**File**: `README.md`
**Action**: UPDATE — add a new section under "🐛 Troubleshooting" (existing section).

**Required content**:

```markdown
### Unit warnings after upgrading to v1.2.3 or later

If you see warnings like:

```
The unit of sensor.mercury_nz_current_bill_7_days is changing, got multiple {None, '$'}
The unit of sensor.mercury_nz_total_usage_7_days (None) cannot be converted to the unit of previously compiled statistics (kWh)
```

…after upgrading to v1.2.3+, this is **expected residue** from prior versions where state attributes
exceeded HA's 16KB cap and `unit_of_measurement` was being dropped from the recorder. v1.2.3 fixed the
upstream cause but stale state rows remain in HA's recorder DB.

**Quick fix** (one-time):

1. Open **Developer Tools → Statistics** in Home Assistant.
2. Find the 3 affected entities (typically: `sensor.mercury_nz_energy_usage`,
   `sensor.mercury_nz_total_usage_7_days`, `sensor.mercury_nz_current_bill_7_days`).
3. Click **"Fix Issue"** next to each.
4. Choose **"Update the unit"**.

The warnings disappear immediately. This does NOT delete the sensor history or the Energy Dashboard
statistics (which use a separate `mercury_co_nz:*` namespace from PR #7).

Alternatively: warnings will resolve on their own as old state rows age out of HA's recorder
(default 10-day retention).
```

### Step 5: Bump manifest

**File**: `custom_components/mercury_co_nz/manifest.json`
**Action**: UPDATE — version `1.2.3` → `1.2.4`.

---

## Patterns to Follow

The state_class fix mirrors HA's own guidance for windowed sums vs cumulative meters. Tibber and Octopus Energy use `state_class=total` for billing-period costs (which can decrease when periods reset).

```python
# SOURCE: const.py:48-54 (existing, correct)
"current_bill": {
    "name": "Current Bill (7 days)",
    "unit": "$",
    "icon": "mdi:currency-usd",
    "device_class": "monetary",
    "state_class": "total",    # CORRECT — bill amount is a running window total
},
```

This is exactly the pattern we're applying to `total_usage`, `hourly_usage`, `monthly_usage` (which were inconsistently tagged `total_increasing`).

---

## Edge Cases & Risks

| Risk / Edge Case                                                                         | Mitigation                                                                                                |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| User runs "Update the unit" on the wrong entity → loses real history                     | UI explicitly asks to confirm. Mercury's Energy Dashboard data is in `mercury_co_nz:*` external statistics, not these entity-level stats. Clearing entity-level stats is safe. |
| User never runs the UI fix → warnings persist for 10 days then auto-resolve              | Acceptable — the warnings are noisy but harmless. Document the auto-resolution path in README.            |
| Changing `state_class` from `total_increasing` to `total` orphans existing long-term stats | HA core handles state_class changes via the SAME Developer Tools → Statistics → Fix Issue flow. User runs the fix once, accepts the new state_class, done. |
| `state_class=total` for a non-monotonic sensor still gets compiled into long-term stats   | Yes — that's the point. `total` allows up/down values. The accumulated sum is approximate but useful.     |
| Other sensors might have similar latent issues                                           | The new `test_state_class_present_for_numeric_sensors` test catches missing state_class. The new `test_windowed_sum_sensors_not_total_increasing` test guards against future regressions. |

---

## Validation

### Automated

```bash
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/
.venv/bin/python -m black --check custom_components/mercury_co_nz/tests/test_state_class.py
.venv/bin/python -c "
from custom_components.mercury_co_nz.const import SENSOR_TYPES
assert SENSOR_TYPES['total_usage']['state_class'] == 'total'
assert SENSOR_TYPES['hourly_usage']['state_class'] == 'total'
assert SENSOR_TYPES['monthly_usage']['state_class'] == 'total'
print('state_class corrected on all 3 windowed-sum sensors')
"
```

### Manual

1. **(immediate)** Run Step 1 user action — confirm warnings disappear.
2. **(after v1.2.4 ships)** Deploy v1.2.4 + restart HA + wait one coordinator cycle.
3. **(after v1.2.4)** Confirm no `total_increasing` warnings ("unexpected dip", "negative state value") for any of the 3 sensors when their windowed sum decreases.
4. Confirm long-term statistics still compile for these 3 sensors (they will — `state_class=total` is supported by recorder).

---

## Scope Boundaries

**IN SCOPE for v1.2.4:**

- Fix latent `state_class=total_increasing` on `total_usage`, `hourly_usage`, `monthly_usage`.
- Add `tests/test_state_class.py` invariant tests.
- README troubleshooting note for the post-v1.2.3 unit warnings.
- Manifest version bump.

**OUT OF SCOPE:**

- **Automated cleanup of HA's recorder DB** — there's no HA API for an integration to clear another entity's compiled statistics. The user MUST run the UI fix. We document it.
- **Removing the `state_class` entirely** to drop these sensors from long-term statistics — would break existing user dashboards/automations that may consume them.
- **Multi-ICP work (issue #5)** — separate plan exists.
- **v1.2.1 diagnostic logging removal** — defer until v1.2.5+ once all the rate/parse stack is confirmed stable.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-27
- **Artifact**: `.claude/PRPs/issues/issue-4-followup-stale-statistics.md`
- **Related**: PR #11 (v1.2.3 attribute fix; correct upstream fix), PR #7 (long-term-stats importer; uses separate namespace so unaffected).
