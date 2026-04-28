# Investigation: Current Rate (and other plan_* sensors) not working

**Issue**: [#6](https://github.com/bkintanar/coopnz/home-assistant-mercury-co-nz/issues/6) (continuing thread; v1.2.0 PR #8 merged 2026-04-26 closed-by code, but plan_* sensors broken in field).
**Type**: BUG
**Investigated**: 2026-04-27

### Assessment

| Metric     | Value     | Reasoning                                                                                                                                          |
| ---------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Severity   | **HIGH**  | All 5 sensors shipped in v1.2.0 are non-functional for at least one confirmed user (ThundaNZ). Maintainer (bkintanar) reproduces independently.    |
| Complexity | LOW       | Diagnostic-logging fix is ~15 lines in `mercury_api.py:get_electricity_plans`. The actual root-cause fix is unknown until user logs are in hand.   |
| Confidence | MEDIUM    | The failure surface (pymercury silently returns None) is well-understood; the exact internal step that fails is unknown without HA logs.            |

---

## Problem Statement

After v1.2.0 (commit `33ac927`, merged 2026-04-26), the 5 new `plan_*` sensors (`sensor.mercury_nz_current_rate`, `_daily_fixed_charge`, `_current_plan`, `_icp_number`, `_plan_change_pending`) appear unavailable / blank in the user's Home Assistant. ThundaNZ confirms in the issue thread: "All original sensors are working apart from the 5 new ones." Maintainer reproduces. Original sensors (bill, monthly, weekly, usage) continue to work — so authentication and the coordinator are healthy. The failure is specifically in the new `plan_*` data path.

---

## Analysis

### 5 Whys

**WHY 1**: Why are the 5 `plan_*` sensors broken?
→ Because `coordinator.data["plan_anytime_rate"]` (and the other 4 `plan_*` keys) are missing → `MercurySensor.native_value` reads `None` and returns `None` (since unit `"NZD/kWh"` is NOT in the `["kWh", "$", "°C", "days", "%"]` zero-fallback list at `sensor.py:148`).
Evidence: `sensor.py:139` `raw_value = self.coordinator.data.get(self._sensor_type)` → None when key absent.

**WHY 2**: Why are `plan_*` keys absent from `coordinator.data`?
→ Because `coordinator.py:119-122` only writes them under `if plans_data:` and `plans_data` is an empty dict.
Evidence: `coordinator.py:119` — `if plans_data:` is False when `get_electricity_plans()` returns `{}`.

**WHY 3**: Why does `MercuryAPI.get_electricity_plans()` return `{}`?
→ Because pymercury's `_api_client.get_electricity_plans(...)` returns `None`. The wrapper's `if not plans: return {}` (`mercury_api.py:495-497`) fires.
Evidence: `mercury_api.py:495-497` — `_LOGGER.warning("No electricity plans data returned")` — this is the warning the user's HA log should contain.

**WHY 4**: Why does pymercury's `get_electricity_plans` return `None`?
→ One of three internal silent-failure paths in `pymercury/api/client.py:get_electricity_plans` (verified by reading installed source at `.venv/lib/python3.13/site-packages/pymercury/api/client.py`):
  1. **A**: pymercury's internal `get_services(customer_id, account_id)` (a SEPARATE API call from what the wrapper feeds in via `complete_data.services`) returns no match for the passed `service_id` → returns `None`.
  2. **B**: A matching service is found but `service.raw_data.get('identifier')` (the ICP number field Mercury uses) is empty/missing → returns `None`.
  3. **C**: ICP is found, the URL is built, but the HTTP `GET` to `electricity_plans` returns non-200 status → returns `None`. (`# pragma: no cover` line in pymercury source.)

Evidence (verbatim from pymercury source, installed at `.venv/lib/python3.13/site-packages/pymercury/api/client.py:get_electricity_plans`):

```python
services = self.get_services(customer_id, account_id)        # A: separate API call
icp_number = None
if services:
    for service in services:
        if service.service_id == service_id and service.service_group.lower() == 'electricity':
            icp_number = service.raw_data.get('identifier')   # B: identifier missing
            if icp_number:
                break

if not icp_number:
    self._log(f"⚠️ Could not retrieve ICP number from services")
    return None                                                # silent return None

url = self.endpoints.electricity_plans(customer_id, account_id, service_id, icp_number)
response = self._make_request('GET', url)
if response.status_code == 200:
    ...
else:  # pragma: no cover
    self._log(f"⚠️ Electricity plans request returned {response.status_code}")
    return None                                                # C: HTTP non-200
```

**WHY 5**: Why does the user not see any of pymercury's diagnostic logs that would distinguish A/B/C?
→ Because pymercury's `_log` method (`pymercury/api/client.py:82-85`) is a no-op unless `verbose=True`:

```python
def _log(self, message: str):
    """Log message if verbose mode is enabled"""
    if self.verbose:
        print(message)
```

The default is `verbose=False` (constructor default). The wrapper instantiates pymercury without overriding this. So pymercury's three "⚠️ Could not retrieve…" / "⚠️ Electricity plans request returned…" diagnostics are **suppressed**.

### ROOT CAUSE (split into two)

1. **The wrapper is blind to which internal step fails inside pymercury**. The user's HA log only shows the wrapper-level `⚠️ No electricity plans data returned` at WARNING — useful as a binary "it failed" signal but not actionable.
2. **The actual reason pymercury returns None for this user's account is one of {A, B, C}** above. Without surfacing pymercury's internal diagnostics OR the wrapper's own pre-check of the same data, we cannot distinguish.

---

### Affected Files

| File                                          | Lines       | Action            | Description                                                                            |
| --------------------------------------------- | ----------- | ----------------- | -------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/mercury_api.py` | 436–510   | UPDATE (diagnostic) | Add diagnostic logging that surfaces which of {A, B, C} failed                         |
| `custom_components/mercury_co_nz/manifest.json` | `version`  | UPDATE             | 1.2.0 → 1.2.1 (diagnostic / debug release)                                              |

The fix in this artifact is **diagnostic-only** — it will surface the actual failure mode in the user's logs. The permanent fix depends on what {A, B, C} we find:
- If A: bypass `get_services` by reading the matching service's `raw_data` from `complete_data.services` (which we already have).
- If B: same as A — `complete_data.services[…].raw_data.get('identifier')` may have the ICP that `get_services` doesn't.
- If C: report to pymercury upstream; possibly add retry-with-account-only fallback URL.

### Integration Points

- `coordinator.py:90` calls `await self.api.get_electricity_plans()` — single call site.
- `mercury_api.py:436-510` is the wrapper method.
- Underlying: `pymercury.api.client.MercuryAPIClient.get_electricity_plans()` (installed source).
- Sensor entity reads: `sensor.py:139` `coordinator.data.get(self._sensor_type)` — pure pass-through.

### Git History

- **Introduced**: `33ac927` (PR #8) — 2026-04-26 — `feat: v1.2.0 — current electricity rate sensors (closes #6)`.
- **Reported broken**: 2026-04-27 by ThundaNZ in issue #6 thread; reproduced by maintainer.
- **Implication**: The wrapper code was correct against pymercury's documented surface, but pymercury's internal silent-failure paths were not anticipated. v1.2.0 shipped with no diagnostic logging surfacing pymercury's internal state.

---

## Implementation Plan

### Step 1: Add wrapper-level diagnostic logging to `get_electricity_plans`

**File**: `custom_components/mercury_co_nz/mercury_api.py`
**Lines**: 478–500
**Action**: UPDATE

**Current code** (`mercury_api.py:478-500`):

```python
service_id = electricity_service.service_id

# Try to get plans using pymercury
try:
    if hasattr(self._client, '_api_client') and hasattr(self._client._api_client, 'get_electricity_plans'):
        plans = await loop.run_in_executor(
            None,
            lambda: self._client._api_client.get_electricity_plans(customer_id, account_id, service_id)
        )
    else:
        _LOGGER.warning("Electricity plans method not available in pymercury")
        return {}
except Exception as api_err:
    _LOGGER.error("Error calling electricity plans API: %s", api_err)
    return {}

if not plans:
    _LOGGER.warning("No electricity plans data returned")
    return {}
```

**Required change** — replace lines 478–500 with:

```python
service_id = electricity_service.service_id

# Diagnostic pre-check (issue #6 follow-up). pymercury's get_electricity_plans
# silently returns None on three internal failure paths; this block surfaces
# which one fires so we can diagnose without enabling pymercury's verbose mode
# (which only prints to stdout, never reaching HA's log).
icp_from_complete_data = None
try:
    icp_from_complete_data = electricity_service.raw_data.get("identifier") if hasattr(electricity_service, "raw_data") else None
except Exception:  # pylint: disable=broad-except
    pass
_LOGGER.info(
    "Mercury plans diagnostic: service_id=%s, service_group=%s, "
    "identifier-from-complete_data=%r",
    service_id,
    getattr(electricity_service, "service_group", "?"),
    icp_from_complete_data,
)

# Cross-check against pymercury's own get_services() which is what its
# get_electricity_plans uses internally. If complete_data has a service that
# get_services doesn't, that's failure mode A. If neither has identifier, B.
try:
    services_for_plans = await loop.run_in_executor(
        None,
        lambda: self._client._api_client.get_services(customer_id, account_id),
    )
    matching = next(
        (s for s in (services_for_plans or [])
         if s.service_id == service_id and s.service_group.lower() == "electricity"),
        None,
    )
    icp_from_get_services = matching.raw_data.get("identifier") if matching else None
    _LOGGER.info(
        "Mercury plans diagnostic: get_services returned %d service(s); "
        "matched-for-our-service_id=%s; identifier-from-get_services=%r",
        len(services_for_plans or []),
        bool(matching),
        icp_from_get_services,
    )
except Exception as diag_err:  # pylint: disable=broad-except
    _LOGGER.warning("Mercury plans diagnostic: get_services pre-check failed: %s", diag_err)

# Try to get plans using pymercury
try:
    if hasattr(self._client, '_api_client') and hasattr(self._client._api_client, 'get_electricity_plans'):
        plans = await loop.run_in_executor(
            None,
            lambda: self._client._api_client.get_electricity_plans(customer_id, account_id, service_id)
        )
    else:
        _LOGGER.warning("Electricity plans method not available in pymercury")
        return {}
except Exception as api_err:
    _LOGGER.error("Error calling electricity plans API: %s", api_err)
    return {}

if not plans:
    _LOGGER.warning(
        "No electricity plans data returned. Diagnostic above shows the failure mode: "
        "(a) get_services empty/no-match, (b) identifier missing, or (c) plans HTTP non-200."
    )
    return {}
```

**Why**: The two new INFO-level logs surface the exact data pymercury sees inside its `get_electricity_plans`. Comparing them lets us distinguish failure modes A vs B vs C from a single user log. Once we know the mode, the permanent fix (next step) is unambiguous.

---

### Step 2: Bump manifest version

**File**: `custom_components/mercury_co_nz/manifest.json`
**Action**: UPDATE — bump `version` from `1.2.0` → `1.2.1`.

**Why**: HACS uses the version field to surface updates. The 1.2.1 release ships diagnostic logging only — no behaviour change for users where `plan_*` sensors already work (TBD whether any such users exist).

---

### Step 3: User deploys 1.2.1 and shares logs (manual)

The maintainer (or any affected user) deploys `1.2.1` via `./deploy.sh` + HA restart, waits one coordinator cycle (~5 min), then opens **Settings → System → Logs** and searches for `Mercury plans diagnostic`. Three INFO lines appear per coordinator update. The user pastes them into the issue.

The diagnostic output reveals one of the three failure modes:

| Pattern in logs                                                                                            | Failure mode | Permanent fix                                                                            |
| ---------------------------------------------------------------------------------------------------------- | ------------ | ---------------------------------------------------------------------------------------- |
| `get_services returned 0 service(s)` OR `matched-for-our-service_id=False`                                 | **A**        | Bypass pymercury's internal `get_services` — extract `identifier` from `complete_data.services` (which we already have) and call the endpoint directly. |
| `identifier-from-complete_data=None` AND `identifier-from-get_services=None`                              | **B**        | The user's Mercury account has no ICP `identifier` in either services list. Likely an account-config issue at Mercury's end. Workaround: surface a clear ERROR with the user's account context; recommend manual support ticket. |
| `identifier-from-complete_data=<some_value>` AND `identifier-from-get_services=<same_value>` AND plans still None | **C**        | The HTTP call itself fails. Add retry, or report to pymercury upstream as a Mercury API regression. |

---

### Step 4: Add the permanent fix (CONDITIONAL on Step 3 outcome)

This step is filled in once the diagnostic logs are received. Possible patterns:

- **For mode A (most likely)**: implement direct-endpoint fallback. Build the URL using `self._client._api_client.endpoints.electricity_plans(customer_id, account_id, service_id, icp_from_complete_data)` and call `self._client._api_client._make_request('GET', url)` — bypassing pymercury's `get_services` step entirely.
- **For mode B**: surface ERROR with account ID and recommend Mercury support ticket; the data simply isn't available via the API.
- **For mode C**: open issue on pymercury repo; potentially add HTTP retry with exponential backoff in our wrapper.

---

### Step 5: Add/Update Tests

**File**: `custom_components/mercury_co_nz/tests/test_plans.py`
**Action**: UPDATE

**Test cases to add**:

```python
def test_get_electricity_plans_returns_empty_on_pymercury_none(monkeypatch) -> None:
    """Wrapper returns {} when pymercury's get_electricity_plans returns None."""
    # Mock the underlying pymercury call to return None; assert wrapper returns {}.
    # Assert the WARNING log line about diagnostic failure mode is emitted.
    ...

def test_diagnostic_logs_surface_complete_data_identifier(caplog) -> None:
    """When complete_data has an identifier, wrapper logs it pre-call."""
    # Mock complete_data.services to have a single electricity service with raw_data identifier.
    # Assert INFO log line includes "identifier-from-complete_data=<value>".
    ...
```

---

## Patterns to Follow

The diagnostic-logging style mirrors existing wrapper diagnostics — see `mercury_api.py:716-727` (`get_usage_data`'s "🔍 Using IDs" log) for the same level of detail.

```python
# SOURCE: custom_components/mercury_co_nz/mercury_api.py:716-727
_LOGGER.info(
    "🔍 Using IDs: customer_id=%s, account_id=%s, service_id=%s",
    customer_id, account_id, service_id,
)
```

---

## Edge Cases & Risks

| Risk / Edge Case                                                          | Mitigation                                                                                                          |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Diagnostic adds an extra `get_services` API call per coordinator cycle    | Yes — adds ~1 HTTP call/5min to Mercury. Minor; can be removed once root cause is fixed in step 4.                  |
| The diagnostic itself raises and breaks unrelated functionality           | The diagnostic block is wrapped in a broad `try/except` that logs at WARNING and continues. Cannot break the wrapper. |
| Multiple users hit different failure modes (some get A, some get C)       | The diagnostic distinguishes by mode; the permanent fix can branch by detected mode.                                |
| Mercury's API endpoint structure changes between v1.0.5 and v1.1.0        | pymercury v1.1.0 audit fixed 15 bugs; possibly one of them changed `get_services` behaviour. Worth checking the pymercury changelog for `get_services` modifications. |

---

## Validation

### Automated Checks

```bash
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/
.venv/bin/python -m black --check custom_components/mercury_co_nz/mercury_api.py
```

### Manual Verification

1. Deploy 1.2.1 via `./deploy.sh`. Restart HA.
2. Wait one coordinator cycle (~5 min).
3. Open **Settings → System → Logs** and search for `Mercury plans diagnostic`.
4. Two INFO lines appear:
   - `service_id=…, service_group=electricity, identifier-from-complete_data=…`
   - `get_services returned N service(s); matched-for-our-service_id=…; identifier-from-get_services=…`
5. Paste into issue #6.
6. Once root cause identified → step 4 of plan → ship 1.2.2 with fix.

---

## Scope Boundaries

**IN SCOPE:**

- Diagnostic logging in `get_electricity_plans` wrapper.
- Manifest version bump 1.2.0 → 1.2.1.
- Tests covering the diagnostic-logging output.

**OUT OF SCOPE:**

- The actual root-cause fix (deferred to step 4, conditional on user logs).
- pymercury upstream patch (depends on what we find).
- Refactoring pymercury's `_log` to use Python's `logging` module (upstream change; out of scope here).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-27
- **Artifact**: `.claude/PRPs/issues/issue-6-current-rate-not-working.md`
- **Related**: PR #8 (v1.2.0 introduced the bug; commit `33ac927` on `main`).
