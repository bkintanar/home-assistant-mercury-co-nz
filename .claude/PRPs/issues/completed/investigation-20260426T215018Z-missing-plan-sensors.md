# Investigation: 3 of 5 v1.2.0 plan_* sensors missing from user's HA

**Issue**: free-form report — "mercury_nz_plan_change_pending, mercury_nz_icp_number, mercury_nz_current_plan. I can't find these sensors. v1.2.0 says it's new but I can't find them."
**Type**: BUG
**Investigated**: 2026-04-27

### Assessment

| Metric     | Value      | Reasoning                                                                                                                                                                                                                                                                          |
| ---------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Severity   | **MEDIUM** | Feature partially broken (3 of 5 v1.2.0 sensors not visible). The 2 functional ones serve the headline use case (HACS dynamic_energy_cost integration); the missing 3 are informational/diagnostic only. Workaround: user can read the same data via attributes on existing entities or pymercury directly. |
| Complexity | **LOW**    | Code review confirms registration loop has no gating; data path delivers values to all 5 keys. Fix is either zero code change (user-side reload/UI-filter) OR a 5-line diagnostic-logging + None-vs-empty-string change in `_normalize_plans_data`.                                  |
| Confidence | **MEDIUM** | The codebase analysis is HIGH-confidence (data path correct end-to-end, no filtering). The ROOT cause requires user-side confirmation — we have 3 plausible hypotheses but cannot distinguish them without seeing the user's Developer Tools → States output and HA logs at DEBUG.    |

---

## Problem Statement

After installing v1.2.0, the user reports they cannot find these 3 entities in Home Assistant:

- `sensor.mercury_nz_current_plan` (`plan_current_plan_name`)
- `sensor.mercury_nz_icp_number` (`plan_icp_number`)
- `sensor.mercury_nz_plan_change_pending` (`plan_is_pending_plan_change`)

The other 2 plan_* sensors added in the same v1.2.0 commit DO work for them:

- `sensor.mercury_nz_current_rate` (`plan_anytime_rate`) — shows numeric value
- `sensor.mercury_nz_daily_fixed_charge` (`plan_daily_fixed_charge`) — shows numeric value

All 5 sensors share a single registration code path with no filtering, gating, or conditional skip; the data flow from Mercury's API → coordinator → entity is identical for all 5. The fact that the working pair returns numeric values and the missing trio returns text values is the only meaningful structural difference.

---

## Analysis

### Code review — what the codebase says SHOULD happen

End-to-end, the 3 missing sensors **should** be registered and **should** carry data:

#### 1. Registration is unconditional

`custom_components/mercury_co_nz/sensor.py:35-43`:

```python
entities = []
for sensor_type in SENSOR_TYPES:
    entities.append(
        MercurySensor(
            coordinator,
            sensor_type,
            config_entry.data.get(CONF_NAME, DEFAULT_NAME),
            config_entry.data[CONF_EMAIL],
        )
    )
async_add_entities(entities)
```

No filter, no `if`, no skip. Every key in `SENSOR_TYPES` becomes a `MercurySensor`.

#### 2. SENSOR_TYPES contains all 5 entries

All 5 plan_* keys live in `const.py:280-314` (added together in commit 33ac927, v1.2.0). Verified by `git log -p -S 'plan_current_plan_name'` — they were added in the same diff, not staggered across releases.

#### 3. `_normalize_plans_data` produces all 5 source keys

`mercury_api.py:655-670`:

```python
normalized = {
    "anytime_rate":              self._parse_rate_amount(anytime_raw, anytime_measure),
    "daily_fixed_charge":        self._parse_rate_amount(daily_raw, None),
    "current_plan_id":           plans_dict.get("current_plan_id") or "",
    "current_plan_name":         plans_dict.get("current_plan_name") or "",   # → entity state
    "current_plan_description":  plans_dict.get("current_plan_description") or "",
    "current_plan_usage_type":   plans_dict.get("current_plan_usage_type") or "",
    "icp_number":                plans_dict.get("icp_number") or "",          # → entity state
    "anytime_rate_measure":      plans_dict.get("anytime_rate_measure") or "",
    "plan_change_date":          plans_dict.get("plan_change_date") or "",
    "can_change_plan":           "yes" if plans_dict.get("can_change_plan") else "no",
    "is_pending_plan_change":    "yes" if plans_dict.get("is_pending_plan_change") else "no",  # → entity state
}
```

All 3 missing-sensor source keys are present. The `or ""` fallback for the text fields ensures the dict always has these keys (even when Mercury returns None).

#### 4. Coordinator prefixes consistently

`coordinator.py:119-122`:

```python
if plans_data:
    for key, value in plans_data.items():
        combined_data[f"plan_{key}"] = value
```

The `if plans_data:` guard is satisfied (we know this because the 2 working sensors got their values). Therefore the loop runs for all 11 normalized keys, producing `coordinator.data["plan_current_plan_name"]`, `["plan_icp_number"]`, `["plan_is_pending_plan_change"]`.

#### 5. `native_value` returns the string

`sensor.py:146` and `sensor.py:237`:

```python
raw_value = self.coordinator.data.get(self._sensor_type)
# … (date handling for date-typed sensors only) …
return raw_value
```

For text sensors, the raw string is returned as-is. The 3 missing sensors should return either an actual value (e.g., `"Off Peak"`, `"0001234567"`, `"yes"/"no"`) or empty string `""`.

#### 6. pymercury exposes all 3 fields

Verified by inspecting the installed pymercury 1.1.0 source — `ElectricityPlans.__init__` sets:

```python
self.icp_number = data.get('icp_number') or data.get('icpNumber') or data.get('icp')
self.current_plan_name = self.current_plan.get('name')
self.is_pending_plan_change = pending_plan.get('isPendingPlanChange', False)
```

These become attributes on the instance, so `__dict__` exposes them to `_normalize_plans_data`.

### So what's actually going wrong?

Code says it should work. User says 3 don't show up. The gap is between "registered in HA" and "user can find in UI". Three plausible hypotheses, ranked by likelihood:

#### Hypothesis A (MOST LIKELY) — entities ARE registered but show empty/`""` state, and the user is not seeing them in default views or filtered lists

Mercury's `/electricity/plans` response shape varies. For some accounts:

- `currentPlan.name` may be missing or `null` → `current_plan_name` ends up as `""` after the `or ""` fallback.
- `icp_number` may live at the service object (Service.icp_number) rather than the plans object — pymercury's `data.get('icp_number') or data.get('icpNumber') or data.get('icp')` returns `None` for accounts where Mercury doesn't echo it on the plans payload, then `or ""` makes it empty.
- `is_pending_plan_change` ALWAYS resolves to `"yes"` or `"no"` (never empty), so this one specifically should be visible. The user reporting it as missing too argues against hypothesis A being the full story.

If A is the cause: entities exist as `sensor.mercury_nz_*` with state `""`, may be ranked low in HA's UI list, and HA's "Entities" search may not surface empty-state sensors prominently.

#### Hypothesis B — integration was upgraded in-place without a config-entry reload, leaving entity-registry only partially in sync

When v1.2.0 added 5 new SENSOR_TYPES keys, HA needs the config entry to be reloaded (or HA itself restarted) so `async_setup_entry` runs again and registers the new entities. The user's having 2 of 5 working argues against this — a partial reload doesn't really exist; either all 5 register or none. But there is a known HA quirk where new entities can appear lazily, especially if the integration's previous setup raised mid-iteration. Worth ruling out.

#### Hypothesis C — entity registry has stale entries from a fork / dev build / community version that conflict on `unique_id`

`unique_id` is `f"{email_hash}_{sensor_type}"`. If the user previously had a different version (e.g., a fork of this integration) that used the same unique_id pattern but registered different entity_ids, HA's entity registry could be silently routing the new entries to disabled/orphaned slots. Less likely, but the registry is the only place where 2-of-5 partial registration is structurally possible.

### Why the 2 working sensors aren't a counter-example

- `plan_anytime_rate` returns a numeric float (e.g., `0.2737`), and HA always elevates numeric sensors with units in default views.
- `plan_daily_fixed_charge` likewise — `NZD/day` unit, numeric.

Numeric sensors have `state_class=measurement`; text sensors have `state_class=None`. HA's frontend treats them differently in default sort / filter behavior.

### Affected Files

| File                                                  | Lines    | Action | Description                                                                                                                                                                            |
| ----------------------------------------------------- | -------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/sensor.py`           | 35-43    | UPDATE | Add INFO-level log when each plan_* entity is constructed: `_LOGGER.info("Registered %s as unique_id=%s", sensor_type, self._attr_unique_id)`. One-line change inside the loop.        |
| `custom_components/mercury_co_nz/mercury_api.py`      | 655-670  | UPDATE | Replace `or ""` for the 3 text sensors with a sentinel — return `None` (or the string `"unknown"`) when source field is None. This makes empty-state entities visible as `unknown` in HA. |
| `custom_components/mercury_co_nz/coordinator.py`      | 119-122  | UPDATE | Add INFO log of the plan_* keys present in `combined_data` after merging: `_LOGGER.info("Plan keys merged: %s", [k for k in combined_data if k.startswith('plan_')])`. Diagnostic only. |
| `README.md`                                           | troubleshooting | UPDATE | Add troubleshooting note: "If you can't find sensor.mercury_nz_current_plan / icp_number / plan_change_pending, check Developer Tools → States; they may show empty state if Mercury doesn't return those fields for your account." |
| `custom_components/mercury_co_nz/tests/test_plans.py` | NEW test | UPDATE | Add explicit test that all 5 plan_* keys are produced by `_normalize_plans_data` even when Mercury's payload is missing the optional fields (currentPlan.name, icp_number).             |

### Integration Points

- pymercury 1.1.0's `ElectricityPlans.__init__` (verified above) — sets all 3 missing fields as attributes.
- `coordinator.py:119` — single guard on the merge loop; needs to remain truthy for any plan_* sensor to work.
- `sensor.py:122-124` — `entity_registry_enabled_default = True` (always-on; no risk these are silently disabled by the integration itself).

### Git History

- v1.2.0 commit `33ac927` (2026-04-27) added all 5 plan_* sensors atomically. No staggered or follow-up commit altered just the 3 missing ones.
- v1.2.1 commit `40e8488` added diagnostic logging to `get_electricity_plans()` (still present, so the user's HA log already shows the raw API response keys at DEBUG).
- v1.2.2 commit `2822379` fixed `_parse_rate_amount` for `'$0.2737'` strings — only affected the 2 numeric sensors.

---

## Implementation Plan

### Step 0 (USER ACTION — diagnostic, do this FIRST)

**Goal**: Confirm whether the entities exist in HA's registry. This determines whether the fix is code-side or user-side.

1. Open Home Assistant → **Developer Tools** → **States** tab.
2. In the entity filter, type `mercury_nz_current_plan`. Look for any entity matching.
3. Repeat for `mercury_nz_icp_number` and `mercury_nz_plan_change_pending`.
4. Report:
   - **(a)** Entities show up with state `""`, `unknown`, `yes`, `no`, etc. → Hypothesis A confirmed; fix is in Step 2 (state visibility).
   - **(b)** Entities show up but are listed under a different entity_id (e.g., `_2` suffix) → Hypothesis C; fix is registry cleanup.
   - **(c)** Entities don't show up at all → Hypothesis B; user reloads the integration (Settings → Devices & Services → Mercury CO NZ → … → Reload), then re-checks.

Also: open **Settings → Devices & Services → Mercury CO NZ → 1 device → All entities** and look for them under "Disabled" or "Hidden".

### Step 1 (DIAGNOSTIC LOGGING — code change, low-risk)

**File**: `custom_components/mercury_co_nz/sensor.py`
**Lines**: 35-43
**Action**: UPDATE

**Current code:**

```python
entities = []
for sensor_type in SENSOR_TYPES:
    entities.append(
        MercurySensor(
            coordinator,
            sensor_type,
            config_entry.data.get(CONF_NAME, DEFAULT_NAME),
            config_entry.data[CONF_EMAIL],
        )
    )
async_add_entities(entities)
```

**Required change:**

```python
entities = []
for sensor_type in SENSOR_TYPES:
    entities.append(
        MercurySensor(
            coordinator,
            sensor_type,
            config_entry.data.get(CONF_NAME, DEFAULT_NAME),
            config_entry.data[CONF_EMAIL],
        )
    )
_LOGGER.info(
    "Mercury CO NZ: registering %d sensor entities: %s",
    len(entities),
    sorted(e._sensor_type for e in entities),
)
async_add_entities(entities)
```

**Why**: Surfaces in the user's HA log exactly which entities the integration ATTEMPTED to register. If `plan_current_plan_name`/`plan_icp_number`/`plan_is_pending_plan_change` are in the list, the issue is downstream of registration (entity registry / UI filtering). If they're missing from the log, the issue is upstream (SENSOR_TYPES not loading correctly, e.g. a syntax-error in const.py somehow swallowed silently).

### Step 2 (STATE VISIBILITY — code change, addresses Hypothesis A)

**File**: `custom_components/mercury_co_nz/mercury_api.py`
**Lines**: 660-669
**Action**: UPDATE

**Current code:**

```python
"current_plan_name":         plans_dict.get("current_plan_name") or "",
"icp_number":                plans_dict.get("icp_number") or "",
"is_pending_plan_change":    "yes" if plans_dict.get("is_pending_plan_change") else "no",
```

**Required change:**

```python
# Don't coerce missing values to empty string — let the entity show "unknown"
# state instead, which makes it visible in HA's UI and signals to the user that
# Mercury didn't return the field.
"current_plan_name":         plans_dict.get("current_plan_name") or None,
"icp_number":                plans_dict.get("icp_number") or None,
# is_pending_plan_change is a real boolean from pymercury — preserve unknown vs. False
"is_pending_plan_change": (
    "yes" if plans_dict.get("is_pending_plan_change") is True
    else "no" if plans_dict.get("is_pending_plan_change") is False
    else None
),
```

**Why**:
- HA shows entities with state `""` differently from `unknown`. Many UI views (especially the Energy Dashboard summary and entity-picker auto-complete) elevate non-empty-state sensors. An entity with state `""` may not appear in default filters; one with state `unknown` is explicitly shown as "I exist but have no value yet".
- For `is_pending_plan_change`, the current code's `"yes" if X else "no"` collapses `None`/`False`/missing → all "no", masking whether Mercury actually returned False vs. didn't return the field. Distinguishing these helps the user diagnose.
- This is a behavior change visible in the entity history. **Acceptable** because the previous behavior (state `""`) was equivalent to "unknown" in semantics anyway — we're just making it explicit.

### Step 3 (COORDINATOR DIAGNOSTIC — code change, low-risk)

**File**: `custom_components/mercury_co_nz/coordinator.py`
**Lines**: 119-122
**Action**: UPDATE

**Current code:**

```python
if plans_data:
    # Add electricity plan data with prefix (issue #6)
    for key, value in plans_data.items():
        combined_data[f"plan_{key}"] = value
```

**Required change:**

```python
if plans_data:
    # Add electricity plan data with prefix (issue #6)
    for key, value in plans_data.items():
        combined_data[f"plan_{key}"] = value
    _LOGGER.info(
        "Mercury CO NZ: plan_* keys in coordinator data after merge: %s",
        sorted(k for k in combined_data if k.startswith("plan_")),
    )
else:
    _LOGGER.warning(
        "Mercury CO NZ: get_electricity_plans returned empty/falsy data; "
        "all plan_* sensors will report None this cycle"
    )
```

**Why**: One-shot per-cycle confirmation that the 11 expected plan_* keys actually land in coordinator.data. If the user's log doesn't show all 11, we know the issue is in `_normalize_plans_data` (something raised an exception silently caught, or `__dict__` doesn't expose what we expect).

### Step 4 (TEST — guards Step 2)

**File**: `custom_components/mercury_co_nz/tests/test_plans.py`
**Action**: UPDATE — add new test

**Test to add:**

```python
def test_normalize_returns_none_for_missing_text_fields():
    """When Mercury's payload omits currentPlan.name/icp_number, normalize
    must return None (not '') so the entity shows 'unknown' in HA, signaling
    the user that the field is genuinely absent.
    """
    api = _api()
    # Simulate pymercury ElectricityPlans where Mercury returned no name/icp
    out = api._normalize_plans_data(_ns(
        anytime_rate="$0.30",
        anytime_rate_measure="$/kWh",
        daily_fixed_charge="$2.00",
        current_plan_name=None,
        icp_number=None,
        is_pending_plan_change=None,  # genuinely unknown, not False
    ))
    assert out["current_plan_name"] is None
    assert out["icp_number"] is None
    assert out["is_pending_plan_change"] is None  # not "no"


def test_normalize_distinguishes_pending_yes_no_unknown():
    """is_pending_plan_change must NOT collapse None and False to 'no'."""
    api = _api()
    yes = api._normalize_plans_data(_ns(is_pending_plan_change=True))
    no = api._normalize_plans_data(_ns(is_pending_plan_change=False))
    unknown = api._normalize_plans_data(_ns(is_pending_plan_change=None))
    assert yes["is_pending_plan_change"] == "yes"
    assert no["is_pending_plan_change"] == "no"
    assert unknown["is_pending_plan_change"] is None
```

### Step 5 (README troubleshooting note)

**File**: `README.md`
**Action**: UPDATE — add to existing 🐛 Troubleshooting section

**Required content:**

```markdown
### Plan / ICP / Plan-change-pending sensors not visible

If you can't find `sensor.mercury_nz_current_plan`, `sensor.mercury_nz_icp_number`,
or `sensor.mercury_nz_plan_change_pending` after upgrading to v1.2.0+:

1. Open **Developer Tools → States** and search for `mercury_nz_current_plan`. The
   entity may exist with state `unknown` if Mercury's API doesn't return that field
   for your account (varies by plan type and account age).
2. Check **Settings → Devices & Services → Mercury CO NZ → device → All entities**.
   The 3 sensors should be listed; if any are listed as "Disabled", click them to
   re-enable.
3. If the entities don't exist at all, click "..." on the integration → **Reload**.
   This re-runs `async_setup_entry` and registers any new sensor types added in
   integration upgrades.
4. Check Home Assistant logs at INFO level for `Mercury CO NZ: registering N
   sensor entities` — this confirms which entities the integration tried to register
   on its last setup pass.

Note: `sensor.mercury_nz_current_rate` (per-kWh price) and
`sensor.mercury_nz_daily_fixed_charge` are the two sensors most users actually need
for HACS dynamic_energy_cost integration. The other 3 are informational.
```

---

## Patterns to Follow

The diagnostic-logging pattern mirrors v1.2.1's diagnostic addition to `get_electricity_plans` (commit 40e8488). One INFO log at registration + one INFO log per coordinator cycle is sufficient — `_LOGGER.debug` would not be visible to most users without log-level changes.

```python
# SOURCE: mercury_api.py (v1.2.1 diagnostic pattern, still in tree)
_LOGGER.info("Mercury plans response: %s", raw_data)
```

The None-vs-empty-string fix mirrors how `bill_payment_method` and `bill_payment_type` work — those text sensors return None when missing, not `""`, and they show as `unknown` in HA.

---

## Edge Cases & Risks

| Risk / Edge Case                                                                                          | Mitigation                                                                                                                                                                       |
| --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User has automations or templates that reference `state == ""` for these sensors                          | Document the change in README + commit message. Empty-string states for these sensors were previously meaningless; very low likelihood of real automations depending on it.        |
| Empty-string → None change breaks downstream consumers expecting a string                                 | The 3 affected sensors return text; HA template engine handles `unknown` and `None` consistently via `is_state_attr`/`states.X.state in ('unknown', '', None)`. Tests guard the change. |
| Diagnostic logging at INFO floods the log on poll-heavy setups (default 5-min interval = 288/day)         | The new INFO logs are 1 per coordinator cycle for the merge log + 1 per integration startup for the registration log. Acceptable volume. Drop to DEBUG if user feedback complains.  |
| The entities ARE registered and the user just isn't searching the right place — code change is unneeded   | Step 0 (Developer Tools → States check) catches this before the code fix is written. If entities are visible there, Steps 1-5 still help future users diagnose similar issues.    |
| pymercury exposes `is_pending_plan_change` as `False` for accounts that DO have an in-flight plan change  | Edge case unlikely; the field comes directly from Mercury's `pendingPlan.isPendingPlanChange` and would be `True` in that scenario. The 3-state version (yes/no/None) is strict.   |

---

## Validation

### Automated

```bash
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/test_plans.py
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/   # full suite — must stay green
```

The new tests in Step 4 must pass; no existing test should regress.

### Manual

1. **(BEFORE merging the code change)** User runs Step 0 diagnostics. If entities are visible in Developer Tools → States with states like `""`, `"unknown"`, `"yes"`, `"no"`: **the code fix in Step 2 is the right intervention**.
2. **(AFTER deploy of v1.2.5/1.3.2)** Restart HA. Check log for `Mercury CO NZ: registering 36 sensor entities` (or whatever the SENSOR_TYPES count is) including all 5 `plan_*` keys.
3. Open Developer Tools → States. Confirm all 3 previously-missing sensors now show:
   - `sensor.mercury_nz_current_plan`: state is plan name string OR `unknown` (not `""`).
   - `sensor.mercury_nz_icp_number`: state is ICP number OR `unknown`.
   - `sensor.mercury_nz_plan_change_pending`: state is `yes`, `no`, OR `unknown`.

---

## Scope Boundaries

**IN SCOPE:**

- Diagnostic logging additions (Steps 1, 3) — pinpoint future regressions.
- None-vs-empty-string normalization fix (Step 2) — makes `unknown` state explicit.
- Test coverage for the changed normalization (Step 4).
- README troubleshooting note (Step 5).
- Manifest version bump (1.3.1 → 1.3.2).

**OUT OF SCOPE:**

- Reorganizing plan_* sensors into a separate platform / device sub-grouping.
- Changing the `state_class`/`device_class` of these sensors to make them more "prominent" in HA's UI — they're correctly classified as text sensors.
- Multi-ICP plan_* (issue #5) — separate plan exists.
- Removing v1.2.1 diagnostic logging from `get_electricity_plans` — keep for now while plan_* stack stabilizes.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-27 (UTC 2026-04-26T21:50:18Z)
- **Artifact**: `.claude/PRPs/issues/investigation-20260426T215018Z-missing-plan-sensors.md`
- **Related**: PR #10 (v1.2.0 plan_* sensors), PR #9 (v1.2.1 diagnostic logging), PR #11 (v1.2.3 attribute fix), PR #13 (v1.3.1 state_class fix).
