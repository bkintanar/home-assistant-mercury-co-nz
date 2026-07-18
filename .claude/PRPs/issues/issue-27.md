# Investigation: Integration not polling and missing information

**Issue**: #27 (https://github.com/bkintanar/home-assistant-mercury-co-nz/issues/27)
**Type**: BUG
**Investigated**: 2026-07-19

### Assessment

| Metric     | Value  | Reasoning                                                                                                                                                              |
| ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Severity   | HIGH   | Every new/recent Mercury customer (no full week/month of billing history yet) gets a hard `AttributeError` that wipes out all monthly, weekly, and bill sensors — no user workaround. |
| Complexity | MEDIUM | The code fix is ~2 lines + a regression test, but it lives in the sibling `pymercury` package and requires a PyPI release plus a version-pin bump in this repo.        |
| Confidence | HIGH   | The stack trace points to the exact line, the crash is a textbook `dict.get(key, default)`-returns-`None`-on-a-`null`-value gotcha, and the buggy code is byte-identical in the released version. |

---

## Problem Statement

For customers who recently joined Mercury (the reporter joined ~2 weeks ago), Mercury's `electricity summary` API returns `"weeklySummary": null` and/or `"monthlySummary": null` because there is not yet a full week/month of billing data. pymercury's `ElectricitySummary.__init__` assumes those keys are either absent or a dict, so it crashes with `'NoneType' object has no attribute 'get'`. The crash is swallowed by the HA integration's per-endpoint `try/except`, so the poll "succeeds" but returns empty weekly/monthly/bill data — every `monthly_*` and `weekly_*` sensor then reports `None` and logs the `sensor.py:189` warning (2303 occurrences), which the user perceives as "not polling / missing information."

---

## Analysis

### Root Cause

`dict.get(key, default)` returns `default` **only when the key is absent**. When the key is present with a value of `null` (JSON) → `None` (Python), `.get()` returns `None`, not the default. Mercury returns `weeklySummary: null` / `monthlySummary: null` for accounts without enough history, so `self.weekly_summary` becomes `None` and the very next line (`self.weekly_summary.get('startDate')`) raises.

### Evidence Chain

WHY: `get_monthly_summary` logs `Error fetching monthly summary data: 'NoneType' object has no attribute 'get'` (328×), and all `monthly_*` / `weekly_usage_history` sensors report `None` → return 0 (2303×).
↓ BECAUSE: the pymercury call that builds the summary object throws before returning.
Evidence: `custom_components/mercury_co_nz/mercury_api.py:291-295` — `electricity_summary = await loop.run_in_executor(None, self._client._api_client.get_electricity_summary, ...)`; the exception is caught at `mercury_api.py:309-322` and the method returns `{}`.

↓ BECAUSE: `get_electricity_summary` constructs `ElectricitySummary(data)` and the constructor raises.
Evidence: `pymercury/api/client.py:513` — `return ElectricitySummary(data)`.

↓ ROOT CAUSE: `ElectricitySummary.__init__` dereferences a `None` weekly/monthly summary.
Evidence: `pymercury/api/models/electricity.py:34-35`
```python
self.weekly_summary = data.get('weeklySummary', {})   # returns None when key present but null
self.weekly_start_date = self.weekly_summary.get('startDate')  # <-- AttributeError
```
Same latent bug at `electricity.py:50-51` for `monthlySummary`.

### Downstream (symptom) files — no change needed, documented for clarity

- `custom_components/mercury_co_nz/mercury_api.py:243-322` (`get_monthly_summary`) — catches the crash, returns `{}`.
- `custom_components/mercury_co_nz/mercury_api.py:127-205` (`get_weekly_summary`) — same call path, same crash, also returns `{}`.
- `custom_components/mercury_co_nz/coordinator.py:77-92` — merges the empty dicts; poll still reports success, so daily/usage sensors keep working while monthly/weekly/bill go to 0.
- `custom_components/mercury_co_nz/sensor.py:182-211` — the `sensor.py:189` warning that fires for every `None` value with a unit (this is the loud symptom, not the cause).

### Affected Files

| File                                                        | Lines     | Action | Description                                                              |
| ----------------------------------------------------------- | --------- | ------ | ------------------------------------------------------------------------ |
| `pymercury/api/models/electricity.py` (repo: bkintanar/pymercury) | 34, 50    | UPDATE | Coerce `null` weekly/monthly summary to `{}` with `... or {}`.           |
| `pymercury/api/models/electricity.py` (defensive)           | 22, 106, 111, 119 | UPDATE | Apply the same `or {}` guard to `summaryInfo`, `pendingPlan`, `currentPlan`, `charges`. |
| `pymercury/api/models/gas.py` (defensive)                   | 19        | UPDATE | Same guard for `content`.                                                |
| `pymercury/api/models/billing.py` (defensive)               | 88        | UPDATE | Same guard for `statement`.                                              |
| `pymercury/tests/test_models_electricity.py`                | ~96 (after) | UPDATE | Add regression tests for `weeklySummary: None` and `monthlySummary: None`. |
| `pymercury/pyproject.toml`                                  | 7         | UPDATE | Bump version `1.1.3` → `1.1.4`.                                          |
| `pymercury/pymercury/__init__.py`                           | (version) | UPDATE | Bump `__version__` `1.1.3` → `1.1.4`.                                    |
| `custom_components/mercury_co_nz/manifest.json` (this repo) | 10, 13    | UPDATE | Pin `mercury-co-nz-api>=1.1.4`; bump integration `version` `1.6.5` → `1.6.6`. |
| `requirements.txt` (this repo)                              | 5         | UPDATE | Pin `mercury-co-nz-api>=1.1.4`.                                          |

### Integration Points

- `custom_components/mercury_co_nz/mercury_api.py:293` and `:176` both call `self._client._api_client.get_electricity_summary(...)` → both hit the crash.
- `pymercury/api/client.py:513` is the only construction site of `ElectricitySummary`.
- The HA integration cannot work around this locally: the exception is raised **inside the constructor**, so no object is ever returned — the only durable fix is upstream in pymercury plus a pin bump.

### Git History

- **pymercury buggy line**: present since `31142b8 feat: added gas and broadband services.`, unchanged through `aef798e fix: audit findings and lift coverage to 100%` — long-standing, not a recent regression.
- **This repo pin**: currently `mercury-co-nz-api>=1.1.3` (`custom_components/mercury_co_nz/manifest.json:10`, `requirements.txt:5`); code is identical in 1.1.3, so bumping without a pymercury fix does nothing.
- **Implication**: latent bug exposed only when a customer's account lacks a full week/month of data (new/recent signups).

---

## Implementation Plan

> This is a **two-repo** fix. Do the pymercury change + release first, then the pin bump in this repo. Both repos are owned by @bkintanar; pymercury is checked out at `/var/www/personal/pymercury`.

### Step 1: Fix the constructor in pymercury

**File**: `pymercury/api/models/electricity.py` (repo `bkintanar/pymercury`)
**Lines**: 34 and 50
**Action**: UPDATE

**Current code:**

```python
# Line 34
self.weekly_summary = data.get('weeklySummary', {})
...
# Line 50
self.monthly_summary = data.get('monthlySummary', {})
```

**Required change:**

```python
# Line 34 — `or {}` handles both absent key AND present-but-null value
self.weekly_summary = data.get('weeklySummary') or {}
...
# Line 50
self.monthly_summary = data.get('monthlySummary') or {}
```

**Why**: `.get('weeklySummary', {})` returns `None` when Mercury sends `"weeklySummary": null`; `or {}` normalizes both the missing and the explicit-null cases to an empty dict, so the subsequent `.get(...)` calls are safe and the existing "no data" branches (which already handle empty dicts, e.g. `electricity.py:69-79`) take over.

---

### Step 2: Defensive guard on the sibling null-prone fields (same file/pattern)

**File**: `pymercury/api/models/electricity.py`
**Action**: UPDATE

Apply the identical `or {}` pattern to the other `.get(key, {})` sites that are then immediately dereferenced, so an unexpected `null` from Mercury never re-triggers this class of crash:

```python
# Line 22  (ElectricityUsageContent)
self.summary_info = data.get('summaryInfo') or {}
# Line 106 (ElectricityPlans)
pending_plan = data.get('pendingPlan') or {}
# Line 111 (ElectricityPlans)
self.current_plan = data.get('currentPlan') or {}
# Line 119 (ElectricityPlans)
charges = self.current_plan.get('charges') or {}
```

**Also** (same class of bug, lower likelihood but cheap):
- `pymercury/api/models/gas.py:19` → `self.content = data.get('content') or {}`
- `pymercury/api/models/billing.py:88` → `self.statement = data.get('statement') or {}`

**Why**: These are the remaining `data.get(k, {})`-then-`.get()` chains; hardening them prevents a whack-a-mole repeat for a different `null` field.

---

### Step 3: Add regression tests in pymercury

**File**: `pymercury/tests/test_models_electricity.py`
**Action**: UPDATE (add to `class TestElectricitySummary`, after the existing `test_with_no_weekly_usage` at line 88-96)

**Test cases to add:**

```python
    def test_with_null_weekly_and_monthly_summary(self):
        # Mercury returns null (not absent) for these keys when the account
        # has < 1 week / < 1 month of billing history (GitHub issue #27).
        s = ElectricitySummary({
            "serviceType": "Electricity",
            "weeklySummary": None,
            "monthlySummary": None,
        })
        # Must not raise AttributeError.
        assert s.weekly_summary == {}
        assert s.monthly_summary == {}
        assert s.weekly_start_date is None
        assert s.monthly_start_date is None
        assert s.weekly_total_usage == 0
        assert s.weekly_usage_days == 0
        assert s.total_kwh_used is None
        assert s.monthly_days_remaining is None
        assert s.monthly_usage_cost is None
```

Mirror the existing style (see `test_with_no_weekly_usage`, `pymercury/tests/test_models_electricity.py:88-96`).

---

### Step 4: Bump pymercury version and release

**Files**: `pymercury/pyproject.toml:7`, `pymercury/pymercury/__init__.py` (`__version__`)
**Action**: UPDATE — `1.1.3` → `1.1.4`

Then run pymercury's test suite (`pytest`) and publish 1.1.4 to PyPI (the project's normal release flow). The pin bump in Step 5 is inert until 1.1.4 is on PyPI, since HACS installs the requirement from PyPI.

---

### Step 5: Bump the pin and integration version in this repo

**File**: `custom_components/mercury_co_nz/manifest.json`
**Lines**: 10 and 13
**Action**: UPDATE

**Current:**
```json
"requirements": ["aiohttp>=3.8.0", "mercury-co-nz-api>=1.1.3"],
...
"version": "1.6.5"
```
**Change to:**
```json
"requirements": ["aiohttp>=3.8.0", "mercury-co-nz-api>=1.1.4"],
...
"version": "1.6.6"
```

**File**: `requirements.txt`
**Line**: 5
**Action**: UPDATE — `mercury-co-nz-api>=1.1.3` → `mercury-co-nz-api>=1.1.4`

**Why**: forces HA/HACS to pull the fixed pymercury; the integration version bump follows this repo's release convention (see recent commits `v1.6.5`, `v1.6.4`).

---

## Patterns to Follow

**Existing empty-data handling the fix relies on (already correct):**

```python
# SOURCE: pymercury/api/models/electricity.py:69-79
# With weekly_summary coerced to {}, weekly_usage is [] and this branch runs.
if weekly_usage:
    ...
else:
    self.total_kwh_used = None
    self.average_daily_usage = None
    self.max_daily_usage = None
    self.min_daily_usage = None
```

**Existing wrapper guard that already tolerates empty summary (no change needed):**

```python
# SOURCE: custom_components/mercury_co_nz/mercury_api.py:222-226
weekly_summary = summary_dict.get("weeklySummary", {})
if not weekly_summary:
    _LOGGER.info(...)
    return {}
```

---

## Edge Cases & Risks

| Risk/Edge Case                                                        | Mitigation                                                                                              |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Mercury sends `weeklySummary: {}` (empty dict, not null)              | Already handled — `{} or {}` is `{}`; existing `if weekly_usage:` else-branch sets fields to `None`.   |
| Only one of weekly/monthly is null                                    | Each line is guarded independently, so partial data still populates the non-null side.                 |
| Pin bumped but pymercury 1.1.4 not yet on PyPI                        | Publish pymercury 1.1.4 first (Step 4) before merging the pin bump (Step 5).                            |
| A different Mercury field returns `null` later                        | Step 2 hardens the other `.get(k, {})`-then-`.get()` chains proactively.                                |
| `sensor.py:189` warnings still noisy for genuinely-empty new accounts | Out of scope; once data exists the warnings stop. Optional follow-up: downgrade to `debug` (see below). |

---

## Validation

### Automated Checks

```bash
# In pymercury repo (/var/www/personal/pymercury):
cd /var/www/personal/pymercury
python -m pytest tests/test_models_electricity.py -v      # new null-summary test must pass
python -m pytest                                          # full suite green

# In this repo:
cd /var/www/personal/home-assistant-mercury-co-nz
python -m pytest custom_components/mercury_co_nz/tests/ -v
```

### Manual Verification

1. Construct `ElectricitySummary({"weeklySummary": None, "monthlySummary": None})` in a Python shell — must **not** raise; `s.weekly_summary == {}` and `s.monthly_summary == {}`.
2. In a HA instance on a recent Mercury account, confirm `custom_components.mercury_co_nz.mercury_api` no longer logs `'NoneType' object has no attribute 'get'` and that regular polling proceeds (the `sensor.py:189` warnings drop off once real weekly/monthly data arrives).

---

## Scope Boundaries

**IN SCOPE:**

- Null-safety for `weeklySummary`/`monthlySummary` (and sibling `null`-prone fields) in `pymercury`.
- pymercury regression test + version bump + release.
- Pin bump (`>=1.1.4`) and integration version bump (`1.6.6`) in this repo.

**OUT OF SCOPE (do not touch):**

- The `sensor.py:182-211` warning logic and per-endpoint `try/except return {}` in `mercury_api.py` — they behave correctly; the empty data is a symptom, not the bug. (Optional future polish: lower the `sensor.py:189` `warning` to `debug` since 0-with-unit is expected for brand-new accounts — defer unless requested.)
- Any refactor of the coordinator's data-merging or JSON-caching flow.
- Broadband/other models beyond the `null`-prone `.get(k, {})` pattern.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-07-19
- **Artifact**: `.claude/PRPs/issues/issue-27.md`
