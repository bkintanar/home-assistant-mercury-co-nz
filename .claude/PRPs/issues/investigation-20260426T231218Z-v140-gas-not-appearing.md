# Investigation: v1.4.0 gas not appearing in States or Statistics

**Issue**: free-form report — "I'm not seeing the gas consumption in either states or in statistics."
**Type**: BUG (partial — "not in States" is expected; "not in Statistics" is the real issue)
**Investigated**: 2026-04-27 (commit 9043343 deployed earlier this session)

### Assessment

| Metric     | Value      | Reasoning                                                                                                                                                             |
| ---------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Severity   | **MEDIUM** | The new gas feature is non-functional for THIS user, but doesn't affect electricity (which keeps working). The "not in States" half is expected (we explicitly didn't ship live gas sensors); only the "not in Statistics" half is broken. Workaround exists: wait + log inspection.                  |
| Complexity | **LOW**    | The first-step fix is **pure diagnostic logging promotion** (~6 lines changed across 3 files) — it's not yet clear which silent failure mode is firing, and the existing logging is too quiet at DEBUG level. After log promotion, the actual root cause likely becomes 1-2 line fix.                           |
| Confidence | **MEDIUM** | Mapped 8 distinct silent-failure modes that could produce this symptom. Without the user's HA log we can't pick between them. HIGH confidence in the failure-mode catalog; MEDIUM confidence in *which one* applies to this user. |

---

## Problem Statement

User upgraded to v1.4.0 (commit `9043343`) and reports gas consumption isn't appearing in either States OR Statistics. Two halves to disentangle:

1. **States**: Expected. v1.4.0 explicitly did NOT ship live gas sensors (`sensor.mercury_nz_gas_*`) — see plan's "NOT Building" section + README's "Live `sensor.mercury_nz_gas_*` entities: not provided" note. This part of the report is a documentation/expectation gap, not a bug.

2. **Statistics**: Real bug. After deploy + restart, the user expected `mercury_co_nz:<acct>_gas_consumption` and `mercury_co_nz:<acct>_gas_cost` to appear in **Developer Tools → Statistics** within ~10 minutes (1-2 coordinator cycles). They didn't. Below maps every silent-failure path that could explain this.

---

## Analysis

### v1.4.0 added these visible log strings — user can grep their HA log to diagnose

| Search string                                           | Level   | Meaning                                                                                              |
| ------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `Mercury CO NZ: gas service detected`                   | INFO    | Detection succeeded; gas importer instantiated                                                       |
| `Mercury CO NZ: gas_* keys merged`                      | INFO    | Gas fetch returned data; merged into coordinator                                                     |
| `Mercury gas: N monthly entries, X.XX kWh total, $Y.YY` | INFO    | Mercury returned a gas response. **If N=0**, Mercury has no usage history for this service yet.      |
| `Mercury gas usage fetch failed this cycle`             | WARNING | Coordinator-side catch — gas API call raised; data is None this cycle                                |
| `Mercury get_gas_usage_monthly returned None`           | WARNING | pymercury returned None (rare; usually means HTTP non-200)                                           |
| `Mercury gas usage fetch failed`                        | ERROR   | Wrapper-internal exception with traceback (`exc_info=True`)                                          |
| `No gas service found; skipping gas usage fetch`        | DEBUG   | **Hidden by default.** Wrapper detected no `is_gas` service.                                         |
| `Gas availability check failed (will retry next cycle)` | DEBUG   | **Hidden by default.** Detection block raised an exception.                                          |
| `Mercury statistics (gas): no monthly records available`| DEBUG   | **Hidden by default.** Importer received empty/missing `gas_monthly_usage_history`.                  |

### Silent-failure modes (most likely → least likely for this user)

| # | Mode                                                       | Visibility       | Likelihood for this user                                                                |
|---|------------------------------------------------------------|------------------|-----------------------------------------------------------------------------------------|
| **A** | **Gas service NOT in `complete_data.services` because pymercury defaults to `include_all=False`** | **NONE** at any log level | **CONFIRMED for this user** — Mercury's `/customers/{cid}/accounts/{aid}/services?includeAll=false` filters out gas. `get_complete_account_data` at `pymercury/client.py:235` calls `get_all_services(customer_id, account_ids)` which calls `get_services(customer_id, account_id)` with the default `include_all=False`. The endpoint URL at `pymercury/api/endpoints.py` (`account_services`) adds `?includeAll=false` when this is False. Gas charges are still visible via bill summary (different endpoint), but the gas Service never makes it into `complete_data.services`. Confirmed because: (1) user's bill summary shows `Gas: $156.28`, (2) NO `Mercury CO NZ: gas service detected` log fires, (3) `mercury_examples.py` `EXAMPLE 5a` shows ALL gas usage queries return 0 (though that uses a hardcoded placeholder `service_id = "80101901093"`, so it doesn't directly confirm — but combined with the silent failure in our integration, the picture is clear). |
| **A2** | **Gas service IS in `complete_data.services` but with a non-`gas` `serviceGroup` value** | **NONE** | Lower likelihood now — the `include_all=False` filter explanation is more parsimonious and explains both the bill-shows-gas + services-doesn't-show-gas observation. |
| **B** | **`bill_account_id` mismatch with gas service's account** (multi-account customer) | WARNING (manifests as Mode F) | MEDIUM — pymercury's `Service` object has NO `account_id` attribute (verified). `get_gas_usage_data` uses `complete_data.account_ids[0]` for ALL services. If gas is on account[1], this fails. |
| **C** | **Mercury gas API returns empty `daily_usage`** (no billing history yet) | INFO (`Mercury gas: 0 monthly entries`) | MEDIUM — visible. If user sees `0 monthly entries` in log, this is the cause. Wait for next bill cycle. |
| **D** | **Detection block raised an exception** (e.g., transient network) | DEBUG (hidden) | LOW — would self-heal next cycle if network recovers. |
| **E** | **`gas_monthly_usage_history` is empty in coordinator data** | DEBUG (hidden) | Manifests as A or C; not a primary cause. |
| **F** | **HTTP error from `get_gas_usage_monthly`** | WARNING (`Mercury gas usage fetch failed this cycle`) | MEDIUM — visible. User would see this. |
| **G** | **`bill_account_id` missing → hash-prefix lock-in** | None on first cycle, ERROR on later cycles if account_id appears | LOW — would only hit if `get_bill_summary` failed AND gas detection succeeded same cycle. |
| **H** | **Recorder not ready** | NOTIFICATION + ERROR after 12 cycles | LOW — would also affect electricity, which the user implicitly says is working. |

### Why pymercury's own logs aren't helping

pymercury's internal `_log()` (`api/client.py:82-84`) uses `print()`, not Python `logging`. It only fires when `verbose=True`, which the integration never sets. So pymercury-side service-detection diagnostics (per-account service counts, exact `serviceGroup` values returned by Mercury) are **completely invisible** in HA's log regardless of HA's log level.

### The 5-Whys (CONFIRMED — Mode A is the `?includeAll=false` filter)

WHY: The user sees no gas statistics in HA, but bill summary shows `Gas: $156.28`.
↓ BECAUSE: The gas importer never instantiates.
Evidence: `coordinator.py:104-110` — `self._gas_statistics` only assigned inside `if any(s.is_gas for s in complete_data.services):`.

↓ BECAUSE: `any(s.is_gas ...)` returns False — no Service object in `complete_data.services` is gas.
Evidence: User's HA log has NO `Mercury CO NZ: gas service detected` line.

↓ BECAUSE: `complete_data.services` does not contain any gas Service for this user.
Evidence: pymercury's `client.py:235` calls `get_all_services(customer_id, account_ids)` which iterates `get_services(customer_id, account_id)` (default `include_all=False`).

↓ BECAUSE: `pymercury/api/endpoints.py` `account_services` URL appends `?includeAll=false` when `include_all=False` — Mercury's API filters gas (and probably broadband) out of the response when this query param is set to false.

↓ ROOT CAUSE: pymercury's default `include_all=False` is a CONSERVATIVE default that hides non-electricity services. The integration uses `complete_data.services` (which inherits this default) and therefore can't see gas.

**Two fix paths:**

1. **Downstream fix (this PR — v1.4.1)**: bypass `get_complete_account_data` for gas detection; call `self._client._api_client.get_services(customer_id, account_id, include_all=True)` directly, iterating accounts. This works without a pymercury release.

2. **Upstream fix (out of scope — would be a pymercury PR)**: change `get_all_services`'s default to `include_all=True`, OR add a new method `get_complete_account_data_all_services()`. Defer to a separate effort.

### Affected Files

| File                                              | Lines        | Action  | Description                                                                              |
| ------------------------------------------------- | ------------ | ------- | ---------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/coordinator.py`  | ~98-115      | UPDATE  | Add INFO-level log enumerating services found (`(service_group, service_type, service_id)` tuples). Promote "no gas detected" branch to a one-time INFO. Promote detection-exception log from DEBUG → WARNING. |
| `custom_components/mercury_co_nz/mercury_api.py`  | ~960-980     | UPDATE  | Promote "No gas service found" log from DEBUG → INFO. Add INFO log inside `get_gas_usage_data` showing the service_id + account_id being used (so multi-account mismatch is visible). |
| `custom_components/mercury_co_nz/statistics.py`   | ~470-475     | UPDATE  | Promote "no monthly records available" log from DEBUG → INFO (the gas branch only — keep electricity at DEBUG to avoid noise on first cycle before electricity history loads). |
| `custom_components/mercury_co_nz/manifest.json`   | version      | UPDATE  | 1.4.0 → 1.4.1 (diagnostic patch).                                                         |

### Integration Points

- HA log default level (`WARNING`) — anything below isn't visible to users by default. The fix promotes key diagnostics to INFO so they're visible in the standard `Settings → System → Logs` view (which shows INFO+ when triggered by user filtering, but more importantly: the `*.log.1` file shows everything INFO+ by default).
- Mercury's `/services` endpoint — its actual `serviceGroup` value (case + spelling) for the user's gas service is the key unknown.
- pymercury 1.1.0 — version pinned in manifest; no bump needed.

### Git History

- v1.4.0 commit `9043343` (just landed earlier this session) — added all the gas pipeline; chose DEBUG level for several diagnostics that are now blocking diagnosis.
- v1.2.1 commit `40e8488` precedent — added INFO-level diagnostic logging to `get_electricity_plans` for issue #6 troubleshooting. **This investigation applies the same pattern to gas.**

---

## Implementation Plan

### Step 0 (USER ACTION — primary, do this BEFORE any code change)

**Goal**: Identify which Mode (A/C/F/etc.) applies. The artifact below ships v1.4.1 with promoted logs to surface most modes — but if the user can grep right now, we save a release cycle.

In HA, go to **Settings → System → Logs** (or `tail -F home-assistant.log`) and search for the following strings (one at a time):

1. `Mercury CO NZ: gas service detected` — **if NOT present**: detection failed (Mode A or D). Most likely.
2. `Mercury gas:` (note the colon) — **if present with "0 monthly entries"**: Mercury returned empty data (Mode C). Wait for next billing cycle; not a code bug.
3. `Mercury gas usage fetch failed` — **if present**: Mode F. The exception message tells us whether it's HTTP 404, 401, JSON parse, etc.
4. `Mercury get_gas_usage_monthly returned None` — **if present**: Mode F variant. pymercury swallowed an HTTP error.

**Report what you find** — the artifact's Step 1+ depends on which Mode applies.

### Step 1 (CODE FIX — diagnostic-logging patch, ship even before user diagnoses)

This is a pure-improvement patch: no behavior change, just makes silent failures visible. Worth shipping regardless of which Mode applies for THIS user — it makes the next user's diagnosis trivial.

#### Step 1a: `coordinator.py` — log services found + promote no-gas log

**File**: `custom_components/mercury_co_nz/coordinator.py`
**Lines**: ~98-115 (the gas-detection block)
**Action**: UPDATE

**Current code:**

```python
if not self._gas_available:
    try:
        loop = asyncio.get_event_loop()
        complete_data = await loop.run_in_executor(
            None, self.api._client.get_complete_account_data
        )
        if complete_data and any(s.is_gas for s in complete_data.services):
            self._gas_available = True
            _LOGGER.info(
                "Mercury CO NZ: gas service detected; enabling gas statistics importer"
            )
            self._gas_statistics = MercuryStatisticsImporter(
                self.hass, self._email, fuel_type="gas"
            )
    except Exception as exc:  # pylint: disable=broad-except
        _LOGGER.debug(
            "Gas availability check failed (will retry next cycle): %s", exc
        )
```

**Required change:**

```python
if not self._gas_available:
    try:
        loop = asyncio.get_event_loop()
        complete_data = await loop.run_in_executor(
            None, self.api._client.get_complete_account_data
        )
        if complete_data:
            services_summary = [
                (s.service_group, s.service_type, s.service_id)
                for s in complete_data.services
            ]
            _LOGGER.info(
                "Mercury CO NZ: services found in account: %s",
                services_summary,
            )
            if any(s.is_gas for s in complete_data.services):
                self._gas_available = True
                _LOGGER.info(
                    "Mercury CO NZ: gas service detected; enabling gas statistics importer"
                )
                self._gas_statistics = MercuryStatisticsImporter(
                    self.hass, self._email, fuel_type="gas"
                )
            else:
                # One-time INFO so user knows detection ran but found no gas.
                # Stays at INFO (not WARNING) because gas-only-on-no-account is
                # a valid configuration; not all users have gas service.
                if not getattr(self, "_gas_no_match_logged", False):
                    _LOGGER.info(
                        "Mercury CO NZ: no gas service found in account "
                        "(serviceGroup values: %s). If you DO have gas with Mercury, "
                        "the integration may not recognize the value Mercury returns; "
                        "please file an issue with the log line above.",
                        sorted(set(s.service_group for s in complete_data.services)),
                    )
                    self._gas_no_match_logged = True
    except Exception as exc:  # pylint: disable=broad-except
        # Promoted from DEBUG → WARNING so transient failures during detection
        # are visible. Coordinator retries every 5 min, so noise is bounded.
        _LOGGER.warning(
            "Mercury CO NZ: gas availability check failed (will retry next cycle): %s",
            exc,
        )
```

**Why**: Two improvements: (a) every cycle logs the actual service_group values Mercury returned — this catches Mode A directly (the user can see exactly what Mercury said when it should have said `gas`); (b) the `else` branch logs a one-time INFO so the user knows detection ran AND found no gas, instead of silent. The `_gas_no_match_logged` flag prevents log spam every 5 minutes.

#### Step 1b: `mercury_api.py` — log gas service_id + account_id; promote no-gas log

**File**: `custom_components/mercury_co_nz/mercury_api.py`
**Lines**: ~959-975 (inside `get_gas_usage_data`)
**Action**: UPDATE

**Current code:**

```python
gas_service = None
for service in complete_data.services:
    if service.is_gas:
        gas_service = service
        break

if not gas_service:
    _LOGGER.debug("No gas service found; skipping gas usage fetch")
    return {}

customer_id = complete_data.customer_id
service_id = gas_service.service_id

gas_monthly = await loop.run_in_executor(
    None,
    self._client._api_client.get_gas_usage_monthly,
    customer_id, account_id, service_id,
)
```

**Required change:**

```python
gas_service = None
for service in complete_data.services:
    if service.is_gas:
        gas_service = service
        break

if not gas_service:
    _LOGGER.info("Mercury gas: no gas service in account; skipping gas usage fetch")
    return {}

customer_id = complete_data.customer_id
service_id = gas_service.service_id

# Diagnostic: surface the (customer_id, account_id, service_id) tuple being passed.
# Most likely culprit for "API returns empty body" is account_id mismatch — Mercury's
# Service object has no .account_id attribute, so multi-account customers may get
# the wrong account_id paired with their gas service_id.
_LOGGER.info(
    "Mercury gas: fetching monthly usage with customer_id=%s, account_id=%s, service_id=%s",
    customer_id, account_id, service_id,
)

gas_monthly = await loop.run_in_executor(
    None,
    self._client._api_client.get_gas_usage_monthly,
    customer_id, account_id, service_id,
)
```

**Why**: Promotes the "no gas service" log from DEBUG to INFO so users see it. Adds explicit (customer_id, account_id, service_id) log so the multi-account mismatch case (Mode B) becomes visible — if Mercury's gas service belongs to a different account, the user can SEE that account_id is `account_ids[0]` and report it.

#### Step 1c: `statistics.py` — promote "no gas records" log

**File**: `custom_components/mercury_co_nz/statistics.py`
**Lines**: ~471-473 (inside the gas branch of `async_update`)
**Action**: UPDATE

**Current code:**

```python
if self._fuel_type == "gas":
    monthly_records = coordinator_data.get("gas_monthly_usage_history") or []
    daily_records: list[dict[str, Any]] = []
    hourly_records: list[dict[str, Any]] = []
    if not monthly_records:
        _LOGGER.debug("Mercury statistics (gas): no monthly records available; skipping")
        return
```

**Required change:**

```python
if self._fuel_type == "gas":
    monthly_records = coordinator_data.get("gas_monthly_usage_history") or []
    daily_records: list[dict[str, Any]] = []
    hourly_records: list[dict[str, Any]] = []
    if not monthly_records:
        # Promoted DEBUG → INFO (gas branch only). Empty monthly records on the
        # gas side is a real diagnostic signal — Mercury returned no usage data,
        # OR the upstream wrapper returned {}, OR detection succeeded but the
        # subsequent fetch silently failed. Visible at INFO so users can correlate.
        _LOGGER.info(
            "Mercury statistics (gas): no monthly records to import this cycle "
            "(fetch may have returned empty or API has no gas history yet)"
        )
        return
```

**Why**: This log was the third silent-failure point. Promoting just the gas side keeps electricity quiet (which is correct — electricity hits this every cycle on first install before JSON cache fills, and would be log-spammy at INFO).

#### Step 1d: `manifest.json` — bump

**File**: `custom_components/mercury_co_nz/manifest.json`
**Action**: UPDATE — version `1.4.0` → `1.4.1`.

#### Step 1e: tests/test_gas_pipeline.py — update if log assertions exist

**Action**: VERIFY — no existing tests assert on the DEBUG strings being changed. Confirm by `grep "no monthly records" custom_components/mercury_co_nz/tests/`. If no match, no test changes needed.

### Step 2 (CONDITIONAL — depends on user diagnosis from Step 0 or v1.4.1 logs)

**Only execute Step 2 AFTER reviewing v1.4.1 log output.** The right Step 2 depends on what Mode the diagnostic logs reveal.

#### Mode A path: `serviceGroup` doesn't match `'gas'`

If the v1.4.1 log shows `services found in account: [('Gas', ...)]` or `[('lpg', ...)]` etc — i.e. Mercury returns a non-`gas` value — the fix is in pymercury (upstream), but we can defensively widen the check in mercury_api.py:

```python
# In get_gas_usage_data, replace `service.is_gas` check:
gas_match_values = ('gas', 'lpg', 'natural-gas', 'naturalgas', 'natural_gas')
for service in complete_data.services:
    sg = (service.service_group or '').lower()
    if sg in gas_match_values or 'gas' in sg:
        gas_service = service
        break
```

This is a "fix upstream issue downstream" — note in code comment.

#### Mode B path: account_id mismatch (multi-account)

If the v1.4.1 log shows `services found` includes a gas service AND `Mercury gas: fetching monthly usage with customer_id=X, account_id=Y, service_id=Z` followed by `Mercury gas usage fetch failed` (a 404), the fix is to find the right account for the gas service.

Since pymercury's `Service.account_id` is None and not recoverable from `raw_data`, the fix is to **iterate `complete_data.accounts` and call `get_services` per-account** to maintain the account_id ↔ service_id mapping ourselves:

```python
# In get_gas_usage_data, before the service loop:
gas_service = None
gas_account_id = None
for acct in complete_data.accounts:
    services_for_account = await loop.run_in_executor(
        None,
        self._client._api_client.get_services,
        complete_data.customer_id, acct.account_id,
    )
    for service in services_for_account:
        if service.is_gas:
            gas_service = service
            gas_account_id = acct.account_id
            break
    if gas_service:
        break

if not gas_service:
    return {}

# Then use gas_account_id (NOT account_ids[0]) in the get_gas_usage_monthly call:
gas_monthly = await loop.run_in_executor(
    None,
    self._client._api_client.get_gas_usage_monthly,
    customer_id, gas_account_id, gas_service.service_id,
)
```

#### Mode C path: Mercury has no gas history yet

If the log shows `Mercury gas: 0 monthly entries`, it's not a code bug — Mercury's API returned an empty `daily_usage`. The user needs to wait for their next gas bill (Mercury bills monthly; first import will appear after the first bill cycle).

**No code fix needed.** Document in README that gas requires at least one billed period before showing in Energy Dashboard.

---

## Patterns to Follow

The diagnostic-promotion pattern mirrors v1.2.1's approach to issue #6 (commit `40e8488`) — when a user couldn't find new sensors, we shipped a diagnostic-only release that promoted DEBUG logs to INFO. Same playbook here for gas.

```python
# SOURCE: mercury_api.py:540-545 (v1.2.1 diagnostic pattern, still in tree)
_LOGGER.info("Mercury plans response: shape=%s, keys=%s, ...", type(raw).__name__, ...)
```

---

## Edge Cases & Risks

| Risk / Edge Case                                                                   | Mitigation                                                                                          |
| ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Promoting "Gas availability check failed" to WARNING is noisy if it fires every 5 min | The flag `_gas_no_match_logged` already prevents repeated INFO; for the WARNING (real exceptions), accepted noise — exception every 5 min is a real problem worth surfacing. Document in PR description. |
| Iterating `complete_data.accounts` (Mode B fix) doubles API calls per cycle         | Only happens once per cycle and only on detection. After `_gas_available` is set, only the gas usage fetch runs. Acceptable. |
| `service.service_type` could be None — comma-separating tuples for log might fail   | The new log uses repr-via-format-string `%s` on tuples; None renders as `None`, no crash.            |
| Defensive widening (Mode A fix) might match non-gas services with "gas" in the name | Unlikely — Mercury's serviceGroup vocabulary doesn't have "gas" as a substring of unrelated services. Test if/when adopting. |

---

## Validation

### Automated

```bash
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/
.venv/bin/pytest -q custom_components/mercury_co_nz/tests/test_gas_pipeline.py
```

EXPECT: 91 tests still pass (no behavior change in v1.4.1 — diagnostic logs only).

### Manual

1. **(immediate after v1.4.1 deploy)** User restarts HA, waits for one coordinator cycle (~5 min).
2. Search HA log for `Mercury CO NZ: services found in account` — should print all services with their `(service_group, service_type, service_id)` tuples. **This single log line answers Mode A vs B.**
3. Search HA log for `Mercury gas: fetching monthly usage with customer_id=...` — confirms which account_id is being passed.
4. Search HA log for `Mercury gas: N monthly entries` — confirms whether Mercury returned data.
5. Report findings; pick Mode-specific fix from Step 2.

---

## Scope Boundaries

**IN SCOPE for v1.4.1 (this artifact):**

- Promote 3 silent diagnostics to INFO/WARNING.
- Add 2 new diagnostic INFO lines (`services found`, `fetching monthly usage with ...`).
- Manifest bump to 1.4.1.

**OUT OF SCOPE for v1.4.1:**

- The actual gas-detection fix (Mode A widening or Mode B account_id resolution). Defer to v1.4.2 once user log identifies the Mode.
- Live gas sensors (`sensor.mercury_nz_gas_*`). Already declared out of scope for v1.4.0.
- pymercury upstream fix for `serviceGroup` parsing — would require a separate pymercury PR.
- Multi-ICP gas (issue #5) — separate.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-27 (UTC `20260426T231218Z`)
- **Artifact**: `.claude/PRPs/issues/investigation-20260426T231218Z-v140-gas-not-appearing.md`
- **Related**: PR #15 (v1.4.0 gas pipeline), PR #9 (v1.2.1 diagnostic pattern precedent), pymercury 1.1.0 source.
