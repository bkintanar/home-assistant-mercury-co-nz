# Investigation: Multiple ICPs on one account

**Issue**: [#5](https://github.com/bkintanar/home-assistant-mercury-co-nz/issues/5)
**Type**: ENHANCEMENT
**Investigated**: 2026-04-27

### Assessment

| Metric     | Value     | Reasoning                                                                                                                                                             |
| ---------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Priority   | MEDIUM    | Affects a real but uncommon segment of NZ Mercury customers (multiple meters on one account); current behaviour silently shows only one ICP's data, which is misleading rather than hard-broken. |
| Complexity | HIGH      | Touches 5 wrapper methods, the coordinator merge, sensor entity creation, the statistics-importer ID lock, and the JSON persistence layer. Existing single-ICP users must keep working without entity-registry orphans. |
| Confidence | HIGH      | Pymercury already exposes the multi-service surface via `get_all_services(...)` and the `services` list; every constraint is in this integration's layer. The single-ICP assumption sites are precisely enumerated below with file:line refs. |

---

## Problem Statement

Mercury Energy NZ allows a single online account to span multiple ICPs (Installation Control Points — separate electricity meters at different premises or for different supply types like main + EV). The integration today reads **only the first electricity service** (`services[0]`) from Mercury's API across every fetch (usage, weekly summary, monthly summary, plans), so users with multiple meters see one ICP's data without any indication, and a "combined" appearance can result if Mercury's API serves an aggregated rollup as the first service. Sensor entity IDs and the new long-term-statistics IDs do not include any per-ICP discriminator, so the integration cannot represent multiple meters even if the wrapper iterated them.

---

## Analysis

### Root Cause

Single-ICP assumption is hard-coded in 5 wrapper methods + 1 coordinator merge + 1 sensor creation loop + 1 statistics ID builder, accumulated over the integration's life as features were added. pymercury 1.1.0 itself is multi-ICP-aware (returns `complete_data.services: list[Service]` with all electricity services across all accounts), so the constraint is entirely in the HA integration layer.

### Single-ICP assumption sites (verbatim)

The pattern `account_id = complete_data.account_ids[0]` followed by `for service in complete_data.services: if service.is_electricity: ...; break` appears in **5 places** in `mercury_api.py`:

| Method                       | `account_ids[0]` line | First-electricity-service `break` |
| ---------------------------- | --------------------- | --------------------------------- |
| `get_weekly_summary`         | 104                   | 107–111                           |
| `get_monthly_summary`        | 220                   | 223–227                           |
| `get_bill_summary`           | 353                   | (account-level — no service loop) |
| `get_electricity_plans`      | 462                   | 469–473                           |
| `get_usage_data`             | 712                   | 715–719                           |

**Verbatim snippet (representative — `get_usage_data:712-719`):**

```python
account_id = complete_data.account_ids[0] if complete_data.account_ids else None
...
electricity_service = None
for service in complete_data.services:
    if service.is_electricity:
        electricity_service = service
        break
```

The `break` discards every electricity service after the first. `complete_data.services` is the result of pymercury's `get_all_services(customer_id, account_ids: List[str])` (`pymercury/api/client.py:235`) which already returns **all** services across **all** accounts.

### Coordinator merge — flat dict, no per-ICP nesting

`coordinator.py:98-122`:

```python
combined_data = usage_data.copy() if usage_data else {}
if bill_data:
    for key, value in bill_data.items():
        combined_data[f"bill_{key}"] = value
# ... same flat-prefix pattern for monthly_, weekly_, content_, plan_
```

Every API call returns scalar data for one ICP and is merged into a single flat dict. A second ICP would collide on every key.

### Sensor creation — flat loop, no ICP iteration

`sensor.py:28-38`:

```python
entities = []
for sensor_type in SENSOR_TYPES:
    entities.append(
        MercurySensor(coordinator, sensor_type, ...)
    )
async_add_entities(entities)
```

`MercurySensor.__init__` at `sensor.py:70-74`:

```python
self._attr_name = f"{name} {sensor_config['name']}"
import hashlib
email_hash = hashlib.md5(email.encode()).hexdigest()[:8]
self._attr_unique_id = f"{email_hash}_{sensor_type}"
```

`unique_id` is `{email_hash_8chars}_{sensor_type}` — no `account_id`, no `service_id`. A second ICP would produce duplicate `unique_id` and HA's entity_registry would reject the second one.

### Statistics importer — single ID per account

`statistics.py:91-96` and `statistics.py:243-244`:

```python
@staticmethod
def _build_id_prefix(account_id: str | None, email_hash: str) -> str:
    if account_id:
        return str(account_id).replace("-", "_").replace(".", "_").lower()
    return f"acct_{email_hash}"
...
account_id = coordinator_data.get("bill_account_id")
candidate = self._build_id_prefix(account_id, self._email_hash)
```

Multiple ICPs on one account would all share `bill_account_id`, producing the same `id_prefix` and hence the same statistic_id. Their kWh totals would merge into one Energy Dashboard series, making per-meter cost analysis impossible.

The `id_prefix` is **persisted via HA's `Store`** (`statistics.py:60-64`) and is **locked on first build** (`statistics.py:245-256`). Switching to a service-id-derived prefix in a future release would trigger the existing ID-flip ERROR and abort imports, requiring the user to manually remove orphaned statistics — by design (this is the safety mechanism added in PR #7 for the energy-dashboard release).

### JSON persistence — single file, not ICP-keyed

`coordinator.py:209` and `coordinator.py:331`:

```
www/mercury_daily.json
www/mercury_hourly.json
```

Both files have a flat `{date: entry}` schema with no ICP namespace. If the wrapper started reading multiple ICPs, the same-date entries would overwrite each other on every coordinator update.

### Config flow — one entry per email, not per ICP

`config_flow.py:56`: `await self.async_set_unique_id(user_input[CONF_EMAIL])`. A second `async_create_entry` with the same email is rejected and routed to a re-auth flow. There is no mechanism today to surface multiple ICPs as separate config entries.

### Frontend cards — entity from config, not hardcoded

`core.js:46-49` (`_getEntity`): cards resolve entities via `this.config.entity` (set per-card by the user). No card hardcodes an entity_id, so a multi-ICP refactor would require users to update their dashboard YAML to point cards at the new ICP-suffixed entity_ids.

---

### Affected Files

| File                                                  | Lines                                          | Action                  | Description                                                                                  |
| ----------------------------------------------------- | ---------------------------------------------- | ----------------------- | -------------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/mercury_api.py`      | 80–158, 196–275, 332–388, 436–510, 688–811     | UPDATE (major)          | Replace single-service selection with iteration; return data keyed by service_id              |
| `custom_components/mercury_co_nz/coordinator.py`      | 98–122, 209, 331                               | UPDATE (major)          | Per-ICP merge into nested `combined_data`; per-ICP JSON files                                 |
| `custom_components/mercury_co_nz/const.py`            | 33–315                                         | UPDATE                  | SENSOR_TYPES stays as-is; entity creation now multiplies it × N ICPs                          |
| `custom_components/mercury_co_nz/sensor.py`           | 19–43, 49–95                                   | UPDATE (major)          | Iterate ICPs; build per-ICP entity name + unique_id; preserve legacy IDs for primary ICP      |
| `custom_components/mercury_co_nz/statistics.py`       | 60–64, 91–96, 234–342                          | UPDATE                  | `id_prefix` includes `service_id`; per-ICP `Store` keys; ID-flip migration path               |
| `custom_components/mercury_co_nz/config_flow.py`      | 50–80                                          | UPDATE                  | Optional ICP selection step (defaults to all)                                                  |
| `custom_components/mercury_co_nz/__init__.py`         | 80–97                                          | UPDATE                  | Coordinator data shape change (informational only)                                             |
| `custom_components/mercury_co_nz/tests/test_*.py`     | (new + updated)                                | CREATE/UPDATE           | New `test_multi_icp.py`; existing tests updated for new data shapes                            |
| `README.md`                                           | (Requirements + new section)                   | UPDATE                  | Document multi-ICP behaviour, entity naming convention, dashboard migration steps              |
| `custom_components/mercury_co_nz/manifest.json`       | `version`                                      | UPDATE                  | 1.2.0 → 2.0.0 (breaking change for multi-ICP users; single-ICP users unaffected via primary-ICP back-compat) |

---

## Implementation Plan

This is a **HIGH-complexity refactor**. The plan below is a strategic overview; an actual implementation should go through `/prp-plan` to produce a detailed step-by-step PRP first.

### Strategy: per-ICP entity discriminator with primary-ICP back-compat

For each electricity service, generate a parallel set of sensors. To preserve existing entity_ids for users who have only one ICP today (the overwhelming majority), designate one ICP as "primary" — its sensors keep the legacy `sensor.mercury_nz_<key>` entity IDs. Additional ICPs get an ICP-prefixed name: `sensor.mercury_nz_<icp_label>_<key>`.

### Step 1 — Coordinator data shape

Change `combined_data` from flat to nested:

```python
combined_data = {
    "_icps": ["ICP_001", "ICP_002"],          # ordered list, [0] is primary
    "_primary_icp": "ICP_001",
    "_account_id": "<account-level>",
    "ICP_001": {                              # per-ICP scalars (today's flat keys)
        "energy_usage": ...,
        "latest_daily_usage": ...,
        "bill_balance": ...,                  # account-level fields duplicated for convenience
        ...
    },
    "ICP_002": { ... },
}
```

Account-level fields (`bill_*`) are duplicated under each ICP key for sensor lookup uniformity, but only fetched once per coordinator update.

### Step 2 — `mercury_api.py` — fetch per ICP

Replace each `get_*` method's single-service selection with a loop. Each method returns a dict `{service_id: {key: value, ...}}` instead of `{key: value, ...}`. The five method signatures change but their internals follow the existing template — every site that does `for service in complete_data.services: if service.is_electricity: ... break` becomes `for service in complete_data.services: if service.is_electricity:` (no break) with the body wrapped to populate a per-service dict.

### Step 3 — `sensor.py` — per-ICP entity creation

```python
for icp_label in coordinator.data["_icps"]:
    is_primary = icp_label == coordinator.data["_primary_icp"]
    for sensor_type in SENSOR_TYPES:
        entities.append(MercurySensor(
            coordinator, sensor_type, name, email,
            icp_label=icp_label,
            is_primary=is_primary,   # primary keeps legacy entity_id
        ))
```

`MercurySensor.__init__`:
- `unique_id = f"{email_hash}_{icp_label}_{sensor_type}"` for non-primary; for primary, keep the existing `f"{email_hash}_{sensor_type}"` to avoid orphaning existing entities.
- `_attr_name = f"{name} {icp_label} {sensor_config['name']}"` for non-primary; primary keeps `f"{name} {sensor_config['name']}"`.
- `native_value` reads `coordinator.data[icp_label][sensor_type]` instead of `coordinator.data[sensor_type]`.

### Step 4 — `statistics.py` — per-ICP statistics IDs

`_build_id_prefix(account_id, service_id, email_hash)` extends the existing two-arg form to include `service_id`. Per-ICP `Store` instances keyed `{DOMAIN}_statistics_{email_hash}_{service_id}`. The `_id_prefix` lock semantics carry over per-ICP.

Migration concern: existing single-ICP users have a locked id_prefix without service_id. The implementation must detect "legacy prefix exists for primary ICP" and continue using it for that ICP (don't flip — that would orphan their Energy Dashboard history). Non-primary ICPs build fresh prefixes.

### Step 5 — Config flow — ICP selection (optional)

Add an `options_flow` allowing users to disable specific ICPs and choose the primary. Default behaviour on first install of multi-ICP: include all, primary = first electricity service. The user can promote a different ICP to primary later, but doing so will orphan the legacy-prefixed entities and is gated behind a confirmation prompt.

### Step 6 — JSON persistence

Either:
- (a) Suffix files: `mercury_daily_<service_id>.json` per ICP. Simpler, larger file count.
- (b) Reshape one file with top-level ICP keys: `{"icps": {"ICP_001": {...}, "ICP_002": {...}}}`. More invasive read/write changes.

Option (a) is preferred — fewer code changes; existing JSON files migrate by being read once with `service_id == coordinator.data["_primary_icp"]` and re-written under the suffixed name.

### Step 7 — Tests

New `test_multi_icp.py` covering: two-ICP coordinator data shape, sensor entity multiplication, primary-ICP back-compat (entity IDs unchanged for one-ICP fixtures), statistics importer per-ICP id_prefix, JSON file migration. Existing tests in `test_statistics.py`, `test_plans.py`, and `test_pymercury_compat.py` update to assert the new data shape.

---

## Patterns to Follow

The five existing `get_*` methods in `mercury_api.py` follow an identical template. The multi-ICP refactor preserves that template — just wraps the post-extraction body in a `for service in electricity_services:` loop and accumulates results in a `{service_id: ...}` dict. No new abstractions needed; the change is mechanical.

---

## Edge Cases & Risks

| Risk / Edge Case                                                                          | Mitigation                                                                                                                                                |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Single-ICP users see entity_ids change → broken dashboards                                | "Primary ICP" mechanism: first ICP keeps the legacy entity_id format; only additional ICPs get suffixed IDs. Single-ICP users see zero change.            |
| Existing Energy Dashboard statistics orphan on next update                                | Statistics importer detects legacy prefix on primary ICP and reuses it; only new ICPs build new prefixes.                                                  |
| User has ICPs across multiple accounts (rare)                                             | `complete_data.services` already spans accounts; the implementation handles this naturally. account-level data (`bill_*`) is duplicated under each ICP.    |
| User changes which ICP is primary (e.g. moves house, sells the meter)                     | Confirmation flow in options_flow; warn that legacy entity history will orphan. Recommend they remove + re-add the integration if they want a clean slate. |
| Mercury renumbers / replaces ICPs (rare but happens)                                      | Statistics ID-flip detection (already implemented for energy-dashboard) catches this and surfaces an ERROR with actionable steps.                          |
| pymercury sometimes returns an "aggregated" service before per-meter services             | If detected (heuristic: name contains "Total" or service_id matches account_id), demote that service in the ICP list and pick the first real meter as primary. |
| TOU plans cross-cut with multi-ICP                                                        | Out of scope for this issue; TOU is already deferred per issue #6 follow-ups.                                                                              |
| Users with smart meters that change ICP IDs mid-billing-period                            | ID-flip protection from PR #7 applies; surfaces actionable error.                                                                                          |

---

## Validation

### Automated

```bash
# In a venv with HA + pymercury installed:
.venv/bin/pytest custom_components/mercury_co_nz/tests/
.venv/bin/python -m mypy --ignore-missing-imports --follow-imports=silent --explicit-package-bases custom_components/mercury_co_nz/
.venv/bin/python -m black --check custom_components/mercury_co_nz/
```

### Manual (multi-ICP user required)

1. Install on an HA instance configured for a Mercury account with ≥2 ICPs.
2. Confirm `Settings → Devices & Services → Mercury → Entities` lists `len(SENSOR_TYPES) × N_ICPs` entities.
3. The first ICP's entities have unsuffixed names (matches single-ICP user behaviour).
4. Additional ICPs have ICP-prefixed names (e.g. `sensor.mercury_nz_icp002_energy_usage`).
5. Energy Dashboard statistics: `Developer Tools → Statistics` shows two `mercury_co_nz:*_energy_consumption` rows, one per ICP.
6. Charts: each frontend card config can be pointed at any ICP's entity_id.

### Single-ICP regression check

1. Install on an HA instance with a single-ICP Mercury account.
2. Confirm entity_ids are **identical** to v1.2.0 — no suffixed names appear.
3. Existing Energy Dashboard statistic IDs continue accruing data without an orphan warning.

---

## Scope Boundaries

**IN SCOPE:**

- Per-ICP sensor entities for all 35+ existing SENSOR_TYPES.
- Per-ICP Energy Dashboard statistics.
- Per-ICP JSON history persistence.
- Optional `options_flow` for selecting primary ICP and disabling unwanted ICPs.
- Backwards compat for existing single-ICP users (zero entity_id changes).
- Migration path for existing Energy Dashboard statistics.

**OUT OF SCOPE:**

- TOU rate sensors (deferred to a separate issue, follow-up to #6).
- Gas / broadband per-service support (architecturally similar but Mercury's data shapes differ).
- Per-ICP tariff/plan diff (the plan_anytime_rate sensor would naturally extend per-ICP without extra work).
- Auto-discovery of new ICPs added to a Mercury account post-install (covered by next coordinator refresh).
- A v2.0 release with breaking-by-default changes (e.g. mandatory ICP suffix on all entities). This plan keeps single-ICP back-compat — a clean v2.0 break could happen later if the maintainer prefers.

---

## Recommended Path Forward

This issue's HIGH complexity warrants a full PRP plan before implementation:

1. **Run `/prp-plan "implement multi-ICP support per investigation/issue-5.md"`** to generate a detailed step-by-step PRP with exact line refs, test cases, and validation commands.
2. The PRP should split the work into sequential commits (e.g. (a) coordinator data shape change with single-ICP back-compat shim, (b) sensor entity multiplication, (c) statistics per-ICP IDs, (d) config_flow options, (e) JSON migration) so each can be merged + tested independently.
3. Recruit a multi-ICP tester before merging — the maintainer doesn't currently have a multi-ICP account (per the comment on the issue).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-27
- **Artifact**: `.claude/PRPs/issues/issue-5.md`
- **Related**: PR #7 (v1.1.0 — Energy Dashboard, on main as `ed94909`); PR #8 (v1.2.0 — current rate sensors, on main as `33ac927`).
