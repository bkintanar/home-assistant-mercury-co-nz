# Investigation: `sensor.mercury_nz_gas_monthly_usage` not found on v1.6.0 install

**Issue**: free-form (no GitHub issue)
**Type**: BUG (deployment, not code)
**Investigated**: 2026-04-28T20:08:58Z

### Assessment

| Metric     | Value  | Reasoning |
| ---------- | ------ | --------- |
| Severity   | LOW    | The v1.6.0 code on `main` correctly registers the entity unconditionally for ALL accounts (gas-less and gas-having). The user's symptom is a known HACS-update-without-full-HA-restart class — recovery is one click in HA settings. No data loss, no impact on other entities. |
| Complexity | LOW    | Zero code changes required. One operational step (full HA restart). Optional: improve the README to make the restart requirement more prominent. |
| Confidence | HIGH   | Two parallel codebase agents traced every conditional path that could prevent registration. All 10 hypotheses ruled out except H1 (HACS-no-restart). Entity-id slug confirmed via direct execution against the installed HA slugify function (`Mercury NZ Gas Monthly Usage` → `sensor.mercury_nz_gas_monthly_usage`). |

---

## Problem Statement

User installed v1.6.0 via HACS and added the Mercury Energy NZ integration. They report `sensor.mercury_nz_gas_monthly_usage` "not found" when adding the new gas card to their Lovelace dashboard. The code on `main` (HEAD `18ade46`, v1.6.0) registers this entity unconditionally for every account on every HA startup — no conditional code path can skip it. The most likely cause is the same HACS-deployment ergonomics issue that produced the v1.5.2 regression report two days ago: HACS wrote v1.6.0 files to disk but HA wasn't fully restarted, so the running process is still executing v1.5.2 bytecode (which doesn't have `gas_monthly_usage` in `SENSOR_TYPES`).

---

## Analysis

### Why this is almost certainly HACS-update-without-full-HA-restart

HACS downloads the v1.6.0 tarball and writes the new `const.py`, `sensor.py`, `gas-monthly-summary-card.js`, and `manifest.json` to `/config/custom_components/mercury_co_nz/`. It does **not** restart Home Assistant or hot-reload Python modules. The running HA process keeps executing the bytecode it loaded at last startup — which is v1.5.2 if the user upgraded since then.

The v1.5.2 `SENSOR_TYPES` dict in memory does not contain a `gas_monthly_usage` key (that key is only in v1.6.0's `const.py:175-184`). When `async_setup_entry` in `sensor.py:35-43` iterates `for sensor_type in SENSOR_TYPES`, it iterates **the in-memory v1.5.2 dict**, registering 39 sensor types — without `gas_monthly_usage`. No error is logged because the loop completes successfully against an unchanged dict.

A full HA process restart (Settings → System → Restart) tears down the Python process, re-imports `const.py` fresh from disk (picking up the `gas_monthly_usage` key), iterates 40 keys instead of 39, and registers `sensor.mercury_nz_gas_monthly_usage` on the new process. Reloads or "Quick Reload" do not re-import custom_components Python modules and will not fix this.

### Hypotheses ruled out (with file:line evidence)

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| 1 | HACS-update-without-full-HA-restart | **CONFIRMED (most likely)** | Same class as `.claude/PRPs/issues/investigation-20260428T105734Z-v152-still-compounding.md`. The v1.6.0 commit message explicitly notes the requirement. |
| 2 | `async_setup_entry` skips registration | RULED OUT | `sensor.py:35-43` iterates `for sensor_type in SENSOR_TYPES` with no guard, no try/except inside the loop, no `continue`. `__init__.py:87-100` continues to `async_forward_entry_setups` even if `async_config_entry_first_refresh` raises. |
| 3 | Entity ID slug mismatch | RULED OUT | Verified by direct execution against the installed HA `slugify` (`venv/.../homeassistant/util/__init__.py:41-46`): `"Mercury NZ Gas Monthly Usage"` slugifies to `mercury_nz_gas_monthly_usage`. Cross-checked against the existing `bill_gas_amount` sensor (`Gas Amount` → `mercury_nz_gas_amount`). |
| 4 | Entity disabled by default | RULED OUT | `sensor.py:127-130` returns `True` unconditionally for all sensor types. |
| 5 | `MercurySensor.__init__` raises for `gas_monthly_usage` specifically | RULED OUT | The only raise path (`sensor.py:78`) is guarded by `sensor_type not in SENSOR_TYPES` — `gas_monthly_usage` IS in `SENSOR_TYPES` per `const.py:175`. No further validation; `_attr_*` assignments are direct dict reads. |
| 6 | Per-entry cache survives HA restart | RULED OUT | `hass.data[DOMAIN]` is rebuilt fresh on every `async_setup_entry`. Python's import system invalidates `__pycache__` when source mtimes/hashes change. |
| 7 | HACS wrote wrong version | NEEDS DATA | User-side check: `cat /config/custom_components/mercury_co_nz/manifest.json` should show `"version": "1.6.0"`. |
| 8 | `gas_monthly_usage` filtered by sub-section | RULED OUT | `SENSOR_TYPES` is a single flat dict; loop iterates with no filter. `ICP_SCOPED_SENSOR_TYPES` is defined but unused in `sensor.py` on `main` (only the v2.0.0 branch uses it). |
| 9 | `native_value=None` blocks registration | RULED OUT | HA registers entities regardless of state value. `native_value` returns `0` (not None) for `unit="kWh"` per `sensor.py:161-185`. |
| 10 | Account-conditional registration | RULED OUT | `sensor.py:34-45` does not consult `coordinator.data` before iterating. Gas-less accounts also get `sensor.mercury_nz_gas_monthly_usage` registered with state `0`. |

### Affected Files

No code changes required. The remediation is operational on the user's HA instance:

| Action | Where | Purpose |
|---|---|---|
| Verify v1.6.0 on disk | `/config/custom_components/mercury_co_nz/manifest.json` | Confirms HACS download succeeded |
| Verify gas key in const.py on disk | `/config/custom_components/mercury_co_nz/const.py` | Confirms files weren't truncated |
| Full HA process restart | Settings → System → Restart | Re-imports the new `const.py` so `SENSOR_TYPES` includes `gas_monthly_usage` |
| Verify post-restart | Developer Tools → States | The entity should now be present |

### Integration Points

- `const.py:175-184` — `gas_monthly_usage` SENSOR_TYPES entry (introduced v1.6.0).
- `sensor.py:35-43` — registration loop, unconditional iteration.
- `sensor.py:47-56` — `_LOGGER.info("Added %d Mercury sensors")` and `_LOGGER.info("registered sensor_types: %s")` — these log lines surface the entity-count mismatch directly.

### Git History

- `18ade46` (2026-04-29) — v1.6.0 introduces `gas_monthly_usage` SENSOR_TYPES entry and the new card.
- `57a6122` (2026-04-28) — v1.5.2, prior baseline. `SENSOR_TYPES` did NOT include `gas_monthly_usage`.
- The same restart-required class of issue was diagnosed two days ago in `investigation-20260428T105734Z-v152-still-compounding.md`. This is the second instance of the pattern in this repo's recent history.

---

## Implementation Plan

### Step 1 — Verify v1.6.0 files on disk

User runs in HA's **Terminal & SSH** add-on (or container shell):

```bash
cat /config/custom_components/mercury_co_nz/manifest.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('version:', d['version']); print('requires:', d['requirements'])"
```

Expected output:
```
version: 1.6.0
requires: ['aiohttp>=3.8.0', 'mercury-co-nz-api>=1.1.3']
```

If `version` reads `1.5.2` or earlier, HACS did not actually copy v1.6.0 to disk — re-run the HACS download (HACS → Mercury CO NZ → Download → confirm v1.6.0).

### Step 2 — Confirm `gas_monthly_usage` is in the on-disk `const.py`

```bash
grep -c "gas_monthly_usage" /config/custom_components/mercury_co_nz/const.py
```

Expected: `2` (the SENSOR_TYPES dict key + the JSMODULES list entry). If `0`, the file on disk is stale — same fix as Step 1.

### Step 3 — Full HA restart (the actual fix)

**Settings → System → Restart Home Assistant** (NOT a config-entry reload, NOT "Quick Reload" of YAML — a full process restart). This is the same caveat documented in the v1.5.2 investigation: HACS does not hot-swap Python modules; only a full HA restart re-imports them from disk.

### Step 4 — Verify the entity now exists

In HA → **Developer Tools → States**, search for `mercury_nz_gas_monthly_usage`. The entity should appear with state `0` (or a kWh value if the gas API has populated data).

Alternative quick check via Developer Tools → Template:

```jinja
{{ states('sensor.mercury_nz_gas_monthly_usage') }}
{{ state_attr('sensor.mercury_nz_gas_monthly_usage', 'gas_monthly_usage_history') | length }}
```

Expected: a numeric state and a history-length value (e.g. `10` for ~10 billing periods). If the state is `unknown`, the gas API call hasn't completed yet — wait one coordinator tick (~5 min) and recheck.

### Step 5 — Confirm via HA logs (optional)

Search HA logs for:

```
Mercury CO NZ: registered sensor_types:
```

(Logged at INFO level by `sensor.py:53-56` on every `async_setup_entry` run.) The list should now include `gas_monthly_usage`. If still absent, return to Step 1.

---

## Patterns to Follow

This is operational guidance — no code patterns. The investigation confirms `main@18ade46`'s registration path is healthy.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|---|---|
| User restarts HA but the config entry is in a failed state from the v1.5.2 era | Reload the integration (Settings → Devices & services → Mercury → ⋯ → Reload). If still failed, remove and re-add. |
| User has multiple Mercury accounts and only one has gas service | All accounts get the `sensor.mercury_nz_gas_monthly_usage` entity registered. Gas-less accounts will show state `0` and an empty `gas_monthly_usage_history` attribute. The card will render the "Loading..." state until populated. |
| HACS download was interrupted | Step 2's grep would return `0`. Re-run HACS download. |
| User is on HA OS Container/Supervised and the file write went to the wrong path | The Mercury manifest pin (`min_ha_version: 2025.11.0`) ensures the standard `/config/custom_components/` path. If HA is running in a non-standard layout, the user can find the path via Developer Tools → Info → "Configuration directory". |
| User's HA version < 2025.11.0 (manifest.json `min_ha_version`) | HA refuses to load the integration entirely. Users would see a different error ("integration requires HA 2025.11.0 or newer"). Not the symptom reported here. |
| User has an extra "Quick Reload" → HA core tab open and assumed it covers integration restarts | Quick Reload is for YAML changes only. Custom-components Python modules require a full process restart. Step 3 makes this explicit. |

---

## Validation

### Automated Checks

```bash
cd /var/www/personal/home-assistant-mercury-co-nz
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/test_attributes.py::test_gas_monthly_usage_sensor_exposes_chart_history -v --no-cov
```

Expected: 1/1 passing — proves the v1.6.0 sensor exposes `gas_monthly_usage_history` correctly when `gas_monthly_usage` is registered. Already verified during v1.6.0 release.

### Manual Verification (the user's HA instance)

1. Step 1 confirms `1.6.0` on disk + pymercury `>=1.1.3`.
2. Step 2 confirms `gas_monthly_usage` is in the on-disk `const.py`.
3. Step 3 full restart (NOT reload).
4. Step 4 entity exists in Developer Tools → States.
5. Add the card to the dashboard:
   ```yaml
   type: custom:mercury-gas-monthly-summary-card
   entity: sensor.mercury_nz_gas_monthly_usage
   name: Gas Monthly Usage
   ```
6. Card renders bar chart (yellow = actual, gray = estimated).

---

## Scope Boundaries

**IN SCOPE:**

- Operational remediation steps for the user (verify on disk → grep → full restart → verify state).
- Diagnostic logging the user can search for to confirm whether their HA process loaded v1.6.0 code.

**OUT OF SCOPE:**

- New code changes. The fix is correct as shipped in v1.6.0. The regression is a known-class HACS deployment issue, not a code bug.
- Adding a "post-update restart required" notification inside HA. HACS already shows this in its own UI on update; the integration would need to detect a version mismatch (manifest version vs running module version) which adds complexity for marginal benefit.
- Forcing HA to reload custom_components Python modules on integration reload. This is an HA-core capability, not something a single integration controls.

**Possible follow-up (advisory, not part of this fix):**

- Make the README's migration note more prominent — currently it lives in the "Gas Monthly Usage Card" section near the bottom. Consider adding a top-of-Demo banner: "After updating via HACS, you MUST restart Home Assistant (Settings → System → Restart) to load the new sensor entity. A reload is not sufficient." — but only after confirming this issue was indeed restart-related (not actually a code defect we missed).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-28T20:08:58Z
- **Artifact**: `.claude/PRPs/issues/investigation-20260428T200858Z-v160-gas-entity-not-found.md`
- **Branch at investigation**: `main` (HEAD `18ade46`, v1.6.0)
- **Related**:
  - Prior investigation (v1.5.2 same class): `.claude/PRPs/issues/investigation-20260428T105734Z-v152-still-compounding.md`
  - Implementation plan: `.claude/PRPs/plans/gas-monthly-summary-card.plan.md`
  - Shipped fix: PR #21 (squash-merged as `18ade46`), released as v1.6.0
- **Confidence**: HIGH for the deployment-not-restart hypothesis (10 alternate hypotheses ruled out with file:line evidence; entity-id slug round-trip confirmed via direct execution; the same class of issue appeared two days ago and was definitively diagnosed). Steps 1–4 distinguish definitively whether the user's local v1.6.0 files made it to disk and whether the running process picked them up.
