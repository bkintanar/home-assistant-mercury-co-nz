# Investigation: `_normalize_plans_data` ValueError on Mercury's `'$0.2737'` rate string

**Issue**: continuation of [#6](https://github.com/bkintanar/home-assistant-mercury-co-nz/issues/6) — discovered via runtime log after v1.2.1 deployment.
**Type**: BUG
**Investigated**: 2026-04-27

### Assessment

| Metric     | Value     | Reasoning                                                                                                                                                              |
| ---------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Severity   | **HIGH**  | Blocks all 5 plan_* sensors from working for ALL users on v1.2.0 / v1.2.1 — pymercury successfully returns data; the wrapper crashes during normalization.              |
| Complexity | LOW       | Fix is localized to `_normalize_plans_data` in `mercury_api.py` — a string-aware parsing helper for the two rate fields (`anytime_rate`, `daily_fixed_charge`).         |
| Confidence | **HIGH**  | The user's HA log gave us the exact ValueError + the literal string Mercury returns (`'$0.2737'`). Verified pymercury extracts `rate.get('rate')` raw — no transformation. |

---

## Problem Statement

The user reports:

```
Logger: custom_components.mercury_co_nz.mercury_api
Source: custom_components/mercury_co_nz/mercury_api.py:613
Error normalizing electricity plans data: could not convert string to float: '$0.2737'
```

This error fires inside `_normalize_plans_data` (the `except Exception as exc:` block at v1.2.1's line 612-614) when calling `float(anytime_cents)` on Mercury's actual response value — which is **a string with a `$` prefix in dollars-per-kWh**, not a numeric value in cents as v1.2.0's normalize code assumed. The exception is caught and the wrapper returns `{}`, so all 5 `plan_*` keys are absent from `coordinator.data`, and all 5 sensors show "unknown".

**v1.2.1's diagnostic logging worked**: it would have run BEFORE this exception (the diagnostic block precedes the pymercury call which precedes normalize), confirming pymercury returned a valid `ElectricityPlans` object. The failure is now narrowed to my normalize code.

---

## Analysis

### 5 Whys

**WHY 1**: Why does `'$0.2737'` reach `_normalize_plans_data`?
→ Because pymercury's `ElectricityPlans.__init__` extracts the rate via `rate.get('rate')` and stores whatever Mercury returns verbatim — no parsing.
Evidence: `pymercury/api/models/electricity.py` (verbatim, both v1.0.5 and v1.1.0):
```python
self.anytime_rate = None
for rate in self.unit_rates:
    if rate.get('name') == 'Anytime':
        self.anytime_rate = rate.get('rate')   # Mercury's raw value
        self.anytime_rate_measure = rate.get('measure')
```

**WHY 2**: Why is Mercury's value a string with `$` prefix?
→ Mercury's `/electricity/plans` API serves rates **formatted for display** (string, with currency symbol, in dollars-per-kWh). This is different from the bill/usage endpoints which serve numeric values. Verified by the user's exact runtime value `'$0.2737'`.

**WHY 3**: Why did v1.2.0's `_normalize_plans_data` assume numeric cents?
→ It assumed Mercury returns rates as numeric values in NZ cents (e.g. `27.37`), based on web research of pymercury examples that used the unit string `"c/kWh"`. That research was based on docstrings, not actual response data.
Evidence: `mercury_api.py:577` (current v1.2.1):
```python
"anytime_rate": round(float(anytime_cents) / 100.0, 6) if anytime_cents is not None else None,
```
Two bugs in this one line:
1. `float('$0.2737')` raises `ValueError`.
2. Even if the `$` were stripped, `0.2737 / 100.0 = 0.002737` — that's 100× too small. The value is already dollars.

**WHY 4**: Why didn't v1.0.5 of pymercury behave differently? (Has anything regressed?)
→ Verified: pymercury v1.0.5 and v1.1.0 extract this field IDENTICALLY (`rate.get('rate')`). Mercury's response format hasn't changed. The bug has existed since v1.2.0 was first written; it just took the v1.2.1 diagnostic release to reveal it.

### ROOT CAUSE

`_normalize_plans_data` does `float(anytime_cents) / 100.0` on a value that's actually `'$0.2737'` (string, dollars). The fix is twofold:
1. Strip non-numeric prefixes (`$`, `c`, `,`, whitespace) before parsing.
2. Decide cents-vs-dollars based on the `anytime_rate_measure` string (`"$/kWh"` → dollars, `"c/kWh"` → cents).

The same bug applies to `daily_fixed_charge` — pymercury extracts it the same way (`charge.get('rate')` for the `'Daily Fixed Charge'` entry in `otherCharges`), so Mercury likely returns `'$1.49'` or similar.

### Affected Files

| File                                             | Lines   | Action | Description                                                                                          |
| ------------------------------------------------ | ------- | ------ | ---------------------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/mercury_api.py` | 565–614 | UPDATE | Replace inline `float(...) / 100.0` with a `_parse_rate_amount(value, measure)` helper that handles strings, units, and missing data. |
| `custom_components/mercury_co_nz/manifest.json`  | version | UPDATE | 1.2.1 → 1.2.2                                                                                         |
| `custom_components/mercury_co_nz/tests/test_plans.py` | append  | UPDATE | Add 5 test cases covering the string-input paths (`'$0.2737'`, `'27.5c'`, malformed, None, dollars-with-comma) |

### Integration Points

- `coordinator.py:90` — calls `await self.api.get_electricity_plans()`. Unchanged.
- `mercury_api.py:436-540` — `get_electricity_plans` method (with v1.2.1 diagnostic logging). Unchanged.
- `mercury_api.py:565-614` — `_normalize_plans_data` (the buggy helper). **Fix here.**
- `const.py:280-310` — SENSOR_TYPES with `unit: "NZD/kWh"` and `"NZD/day"`. **Unchanged** — the units are already correct for dollars-per-kWh / dollars-per-day. We just need the value in the right unit.

### Git History

- **Introduced**: commit `33ac927` — 2026-04-26 — `feat: v1.2.0 — current electricity rate sensors (closes #6)`. The normalize helper has had this bug since the initial v1.2.0 ship.
- **Diagnostic added**: commit `40e8488`/`e5c2e2d` — 2026-04-26 — `fix: v1.2.1 — diagnostic logging for plan_* sensors`. Made the bug observable without changing behaviour.
- **Implication**: original-bug, not a regression. The bug was in v1.2.0 from the start; v1.2.1's diagnostic logging revealed it.

---

## Implementation Plan

### Step 1: Add `_parse_rate_amount` helper to `MercuryAPI`

**File**: `custom_components/mercury_co_nz/mercury_api.py`
**Action**: ADD a new method (place near `_normalize_plans_data`, around line 560).

**Required code**:

```python
@staticmethod
def _parse_rate_amount(value: Any, measure: str | None = None) -> float | None:
    """Parse a Mercury rate value into a float in NZD per the unit (kWh/day).

    Mercury's /electricity/plans endpoint returns rates as DISPLAY-FORMATTED
    strings with a currency prefix — e.g. ``'$0.2737'`` for dollars-per-kWh,
    or ``'27.37c'`` if Mercury ever serves a cents-form (defensive). Other
    endpoints (bill, weekly, monthly) return numeric values, so this helper
    lives only in the plans-data normalization path.

    Args:
        value: Mercury's rate value (string, int, float, or None).
        measure: The companion ``rate_measure`` string (e.g. ``'$/kWh'``,
            ``'c/kWh'``, or empty). Used to decide cents-to-dollars conversion.

    Returns:
        Float in NZD per (kWh / day) — i.e. dollars, never cents. ``None`` if
        the input is missing or unparseable.
    """
    if value is None:
        return None

    # If pymercury ever returns a numeric type, treat it as already canonical
    # (dollars). The current Mercury API delivers strings; this branch is
    # defensive for future format changes.
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        # Strip currency prefix/suffix and thousands separator. Defensive
        # against any of these characters appearing in Mercury's strings.
        cleaned = (
            str(value)
            .strip()
            .replace("$", "")
            .replace(",", "")
            .rstrip("c")  # strip trailing 'c' for "27.37c" form (defensive)
        )
        try:
            numeric = float(cleaned)
        except ValueError:
            _LOGGER.warning(
                "Mercury plans: could not parse rate %r (measure=%r); returning None",
                value, measure,
            )
            return None

    # Cents → dollars only if the measure explicitly says cents. Mercury
    # actually returns dollars (verified by user runtime data); the cents
    # branch is defensive for future format variation.
    if measure and "c" in measure.lower() and "$" not in measure:
        numeric = numeric / 100.0

    return round(numeric, 6)
```

**Why**: One canonical helper that's robust to Mercury's actual `'$0.2737'` format AND future variations. Logs at WARNING when parsing fails so the user can see the unparsed value.

---

### Step 2: Update `_normalize_plans_data` to use the helper

**File**: `custom_components/mercury_co_nz/mercury_api.py`
**Lines**: 565–614 (the body of `_normalize_plans_data`)
**Action**: UPDATE — replace the two `round(float(value) / 100.0, 6) if value is not None else None` expressions with calls to `_parse_rate_amount`.

**Current code** (mercury_api.py:573-580 area):

```python
anytime_cents = plans_dict.get("anytime_rate")
daily_cents = plans_dict.get("daily_fixed_charge")

normalized = {
    # Numeric (NZD)
    "anytime_rate": round(float(anytime_cents) / 100.0, 6) if anytime_cents is not None else None,
    "daily_fixed_charge": round(float(daily_cents) / 100.0, 6) if daily_cents is not None else None,
    ...
```

**Required change**:

```python
# Mercury serves rates as strings with currency prefix (e.g. "$0.2737"),
# in dollars-per-kWh. The helper handles the string → float conversion and
# uses the rate_measure field to disambiguate cents/dollars defensively.
anytime_raw = plans_dict.get("anytime_rate")
daily_raw = plans_dict.get("daily_fixed_charge")
anytime_measure = plans_dict.get("anytime_rate_measure")
# Mercury doesn't expose a separate measure for daily_fixed_charge in
# pymercury's model; it's always per-day in dollars. Pass None.

normalized = {
    "anytime_rate": self._parse_rate_amount(anytime_raw, anytime_measure),
    "daily_fixed_charge": self._parse_rate_amount(daily_raw, None),
    ...
```

**Why**: Replaces two buggy inline expressions with one tested helper. The change is mechanically simple and the helper centralises future format-handling.

---

### Step 3: Bump manifest version

**File**: `custom_components/mercury_co_nz/manifest.json`
**Action**: UPDATE — `version` from `1.2.1` → `1.2.2`.

---

### Step 4: Add tests

**File**: `custom_components/mercury_co_nz/tests/test_plans.py`
**Action**: APPEND new test cases. Include both pure-helper tests of `_parse_rate_amount` and integration tests of `_normalize_plans_data` with the new shape.

**Test cases to add**:

```python
# --- _parse_rate_amount helper tests ---

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
    """A bare numeric '27.5' with measure='c/kWh' is interpreted as cents → 0.275 NZD."""
    assert MercuryAPI._parse_rate_amount("27.5", "c/kWh") == 0.275


def test_parse_rate_amount_numeric_dollars_passthrough() -> None:
    """A bare float (no measure) is treated as already canonical dollars."""
    assert MercuryAPI._parse_rate_amount(0.2737, None) == 0.2737


def test_parse_rate_amount_returns_none_for_none() -> None:
    assert MercuryAPI._parse_rate_amount(None, "$/kWh") is None


def test_parse_rate_amount_returns_none_for_unparseable(caplog) -> None:
    """Malformed input → None + WARNING log."""
    import logging
    with caplog.at_level(logging.WARNING):
        result = MercuryAPI._parse_rate_amount("not a number", "$/kWh")
    assert result is None
    assert any("could not parse rate" in r.getMessage() for r in caplog.records)


def test_parse_rate_amount_zero_is_preserved() -> None:
    """Free-power period (0.0) must NOT become None."""
    assert MercuryAPI._parse_rate_amount("$0.00", "$/kWh") == 0.0
    assert MercuryAPI._parse_rate_amount(0, "$/kWh") == 0.0


# --- _normalize_plans_data with the actual Mercury format ---

def test_normalize_handles_dollar_string_anytime_rate() -> None:
    """Regression test for the bug from issue #6 logs."""
    plans = _ns(
        anytime_rate="$0.2737",
        anytime_rate_measure="$/kWh",
        daily_fixed_charge="$1.49",
        current_plan_name="Anytime",
    )
    out = _api()._normalize_plans_data(plans)
    assert out["anytime_rate"] == 0.2737
    assert out["daily_fixed_charge"] == 1.49


def test_normalize_does_not_raise_on_dollar_string() -> None:
    """The original ValueError must NOT be raised for the actual Mercury format."""
    plans = _ns(anytime_rate="$0.2737", anytime_rate_measure="$/kWh")
    # Should not raise
    out = _api()._normalize_plans_data(plans)
    # Should produce a valid normalized dict, not {}
    assert out != {}
    assert out["anytime_rate"] == 0.2737
```

---

## Patterns to Follow

The existing `_normalize_*` helpers in `mercury_api.py` use defensive `.get(default)` patterns and log at ERROR when the whole helper fails. The new `_parse_rate_amount` helper logs at WARNING (not ERROR) for unparseable individual values because the rest of the dict can still be useful — only the affected rate field becomes `None`.

```python
# SOURCE: custom_components/mercury_co_nz/mercury_api.py:432-434 (existing _normalize_bill_data)
except Exception as exc:
    _LOGGER.error("Error normalizing bill data: %s", exc)
    return {}
```

The new helper preserves this whole-helper error path AND adds per-field WARNING for individual field parse failures.

---

## Edge Cases & Risks

| Risk / Edge Case                                                                                  | Mitigation                                                                                                            |
| ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Mercury changes the rate format (e.g. drops `$` prefix, switches to cents) without notice         | The helper is permissive: strips `$`/`c`/`,` and uses `measure` as the unit hint. New formats may need helper updates. |
| `measure` field is empty/missing                                                                  | Helper defaults to "treat as dollars" (Mercury's actual behaviour today). If Mercury returns cents without a measure, value is wrong by 100×. Acceptable — extremely unlikely. |
| Whole-helper exception (e.g. `__dict__` access fails)                                             | Existing `except Exception as exc: return {}` block at line 612-614 still catches; new helper just makes most successful paths actually succeed. |
| Mercury returns scientific notation `"1.234e-1"`                                                  | `float()` parses it. Edge case; covered.                                                                              |
| Mercury returns multiple decimal points `"$0.27.37"`                                               | `float()` raises ValueError → helper logs WARNING + returns None for that field. Other fields unaffected.              |

---

## Validation

### Automated

```bash
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/test_plans.py
.venv/bin/python -m black --check custom_components/mercury_co_nz/tests/test_plans.py
.venv/bin/python -m mypy --ignore-missing-imports --follow-imports=silent --explicit-package-bases custom_components/mercury_co_nz/tests/test_plans.py
```

**EXPECT**: All 46 existing + 9 new tests pass. Specifically the regression test `test_normalize_handles_dollar_string_anytime_rate` must pass — that's the one that would have caught the bug.

### Manual

1. Deploy 1.2.2 via `./deploy.sh` + HA restart.
2. Wait one coordinator cycle (~5 min).
3. Settings → Devices & Services → Mercury → entities. Confirm:
   - `sensor.mercury_nz_current_rate` shows a numeric NZD value matching your bill (e.g. `0.2737`).
   - `sensor.mercury_nz_daily_fixed_charge` shows a numeric NZD/day value.
   - `sensor.mercury_nz_current_plan` shows the plan name.
   - `sensor.mercury_nz_icp_number` shows the ICP.
   - `sensor.mercury_nz_plan_change_pending` shows `yes`/`no`.
4. Confirm NO `Error normalizing electricity plans data` lines in HA logs.
5. (Optional) Configure HACS dynamic_energy_cost with `sensor.mercury_nz_current_rate` as price source; verify cost output is correct against a hand calculation.

---

## Scope Boundaries

**IN SCOPE:**

- Fix `_normalize_plans_data` to handle Mercury's actual `'$0.2737'` format.
- Add `_parse_rate_amount` helper.
- Tests covering the regression + edge cases.
- Manifest version bump.

**OUT OF SCOPE:**

- v1.2.1's diagnostic logging block stays in place (will be removed in 1.2.3 once we're confident the parse fix is sufficient — keeping it for now to catch any further surprises).
- The `_NOTIFICATION_ID` and `_async_load_persisted_prefix` race fixes from prior session work — separate PRs.
- TOU (Time-of-Use) plans where `unit_rates` doesn't have an `'Anytime'` entry — pymercury sets `anytime_rate=None` for those; the helper returns None; sensor reads "unknown". This is correct behaviour for TOU plans; the proper fix is to expose Day/Night sensors separately (deferred per v1.2.0's NOT Building list).
- pymercury upstream change to surface formatted-string rates as parsed floats — out of our control; we work around it.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-27
- **Artifact**: `.claude/PRPs/issues/issue-6-rate-parse-error.md`
- **Related**: PR #8 (v1.2.0; introduced the bug), PR #9 (v1.2.1; diagnostic that surfaced it). The next PR (v1.2.2) actually fixes the bug.
