# Investigation: Option to pin a single ICP per HA instance

**Issue**: #30 (https://github.com/bkintanar/home-assistant-mercury-co-nz/issues/30)
**Type**: ENHANCEMENT
**Investigated**: 2026-07-20

### Assessment

| Metric     | Value  | Reasoning                                                                                                                                             |
| ---------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Priority   | MEDIUM | Real, specifically-requested use case (@LanlinkNZ runs one HA instance per address on a single multi-ICP account) but niche and non-blocking.        |
| Complexity | MEDIUM | ~4 files (const, config_flow, coordinator, __init__) + tests; builds directly on the v2.0.0 per-`{service_id}` data layer, so low architectural risk. |
| Confidence | HIGH   | The whole thing cascades from one function: filtering `_discovered_electricity_services` + `_primary_service_id` in `_discover_icps_if_needed` scopes entities (`sensor.py:69`), account-scoped summaries (top-level keys), and charts to the chosen ICP. |

---

## Problem Statement

v2.0.0 exposes every ICP on an account as its own device/entities, but the account-scoped sensors — `weekly_*`, `monthly_*` summaries, and the usage charts fed by them — still show the **primary/combined** ICP's data. A user running one HA instance per physical address (meters on one Mercury account) wants each instance to show **only that address's ICP** everywhere. Add an integration **options** setting to pin a single ICP; when set, the whole integration scopes to it.

---

## Analysis

### Change Rationale (how the current architecture makes this a small, well-contained change)

The v2.0.0 coordinator already fetches and stores **per-`{service_id}`** data for usage, weekly, monthly, and plans. It writes each ICP's data twice: the **primary** ICP's values go to **top-level keys** (`total_usage`, `monthly_*`, `weekly_*`, `plan_*`), and **all** ICPs also get `icp_<token>_<key>` keys. Account-scoped sensors read the **top-level** keys — i.e. the **primary** ICP's slice.

Therefore, **if the user's selected ICP becomes the primary AND the only discovered ICP for this instance**, every surface scopes to it automatically:
- `sensor.py:69` iterates `coordinator._discovered_electricity_services` → only the selected ICP's ICP-scoped entities are created.
- Account-scoped `weekly_*`/`monthly_*` sensors read top-level keys = the selected ICP's slice (because it's primary).
- The usage/summary charts read those entities → scoped.

So the entire feature reduces to: **honor an options value inside `_discover_icps_if_needed`** (filter + set primary), plus the plumbing to expose the option and reload on change.

### Key code (current v2.0.0 state)

Discovery designates primary as `services[0]` and builds the ICP list — `coordinator.py:310-344`:
```python
self._discovered_electricity_services = [
    s for s in complete_data.services if s.is_electricity
]
...
if self._discovered_electricity_services:
    self._primary_service_id = (
        self._primary_service_id
        or self._discovered_electricity_services[0].service_id
    )
    # persisted to config_entry.data["_primary_service_id"]
...
for s in self._discovered_electricity_services:
    is_primary = s.service_id == self._primary_service_id
    self._importers[("electricity", s.service_id)] = MercuryStatisticsImporter(...)
```

Entity creation iterates the discovered list — `sensor.py:68-79`:
```python
for service in coordinator._discovered_electricity_services:
    is_primary = service.service_id == coordinator._primary_service_id
    for sensor_type in ICP_SCOPED_SENSOR_TYPES:
        entities.append(MercurySensor(coordinator, sensor_type, name, email,
            service_id=service.service_id, is_primary=is_primary, fuel_type="electricity"))
```

Account-scoped summary sensors read top-level (primary) keys — `coordinator.py:156-172` writes `monthly_*`/`weekly_*` from the primary ICP's per-service dict.

`config_flow.py` currently has **no** OptionsFlow. `__init__.py` `async_setup_entry` (63-104) has **no** options-update listener.

### Affected Files

| File | Lines | Action | Description |
| --- | --- | --- | --- |
| `custom_components/mercury_co_nz/const.py` | ~27 | UPDATE | Add `CONF_ICP = "icp"` config key |
| `custom_components/mercury_co_nz/config_flow.py` | 27-34, +new | UPDATE | Add `async_get_options_flow` + `MercuryOptionsFlow` (ICP selector from discovered services) |
| `custom_components/mercury_co_nz/coordinator.py` | 287-344 | UPDATE | In `_discover_icps_if_needed`, honor `entry.options[CONF_ICP]`: filter `_discovered_electricity_services` to the selected ICP and set it primary |
| `custom_components/mercury_co_nz/__init__.py` | 63-104 | UPDATE | Add options-update listener → reload entry on option change |
| `custom_components/mercury_co_nz/tests/test_multi_icp.py` | append | UPDATE | Tests: option filters to one ICP; account-scoped sensors read selected slice; unset = current behavior |
| `custom_components/mercury_co_nz/manifest.json` | 13 | UPDATE | version `2.0.0` → `2.1.0` (new feature) |

### Integration Points

- `hass.data[DOMAIN][entry.entry_id]` holds the live coordinator → the OptionsFlow reads `coordinator._discovered_electricity_services` to populate ICP choices.
- `entry.options` (not `entry.data`) stores the selection — standard HA options pattern; changing it fires the update listener → reload → `_discover_icps_if_needed` re-runs with `self._discovered = False` on the fresh coordinator.
- Statistics: with the selected ICP as sole primary, its `statistic_id`/Store key = the legacy account-based id. On **separate** HA instances (LanlinkNZ's case) this is fine — each instance has its own recorder DB.

### Git History

- Multi-ICP scaffolding (`ICP_SCOPED_SENSOR_TYPES`, `_discover_icps_if_needed`, per-`{service_id}` data) introduced in **v2.0.0** (PR #18, merged 2026-07-20, commit `21caf59`). This issue is the planned follow-up noted in that PR's release notes.

---

## Implementation Plan

### Step 1: Add the config key

**File**: `custom_components/mercury_co_nz/const.py`  •  **Action**: UPDATE (near line 27)
```python
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_ICP = "icp"  # options: pin a single electricity ICP (service_id) for this instance
```

### Step 2: OptionsFlow with an ICP selector

**File**: `custom_components/mercury_co_nz/config_flow.py`  •  **Action**: UPDATE

Add the import and an options-flow accessor on `MercuryConfigFlow`, plus the handler class:
```python
from homeassistant.core import callback
from .const import DOMAIN, CONF_EMAIL, CONF_ICP

class MercuryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    ...
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MercuryOptionsFlow(config_entry)


class MercuryOptionsFlow(config_entries.OptionsFlow):
    """Options: pin a single ICP for this HA instance."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # empty string ⇒ clear selection (show all ICPs / current behavior)
            icp = user_input.get(CONF_ICP) or None
            return self.async_create_entry(title="", data={CONF_ICP: icp})

        # Populate choices from the live coordinator's discovered ICPs.
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        services = getattr(coordinator, "_discovered_electricity_services", []) or []
        options = {s.service_id: f"ICP {s.service_id}" for s in services}

        if not options:
            # Discovery hasn't completed yet — can't list ICPs.
            return self.async_abort(reason="icps_not_discovered")

        current = self.config_entry.options.get(CONF_ICP)
        # "" sentinel = All ICPs (default multi-ICP behavior)
        choices = {"": "All ICPs (default)", **options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_ICP, default=current or ""): vol.In(choices),
            }),
        )
```
**Why**: standard HA OptionsFlow; choices come from live discovery so the user picks a real ICP; `""` clears back to default.

### Step 3: Honor the option in discovery

**File**: `custom_components/mercury_co_nz/coordinator.py`  •  **Action**: UPDATE (inside `_discover_icps_if_needed`, after building `_discovered_electricity_services` at 310-315)
```python
self._discovered_electricity_services = [
    s for s in complete_data.services if s.is_electricity
]
self._discovered_gas_services = [
    s for s in complete_data.services if s.is_gas
]

# Option (#30): pin a single ICP for this instance. When set to a valid
# service_id, scope the whole integration to it — it becomes the sole
# discovered electricity ICP AND the primary, so every account-scoped
# sensor + chart reads its slice and no other ICP entities are created.
selected_icp = self._config_entry.options.get(CONF_ICP)
if selected_icp:
    match = [s for s in self._discovered_electricity_services
             if s.service_id == selected_icp]
    if match:
        self._discovered_electricity_services = match
        self._primary_service_id = selected_icp
    else:
        _LOGGER.warning(
            "Mercury CO NZ: pinned ICP %s not found among discovered services "
            "%s; ignoring option and using all ICPs",
            selected_icp,
            [s.service_id for s in self._discovered_electricity_services],
        )
```
Then guard the existing primary default so the option wins — the block at 318-322 already uses `self._primary_service_id or services[0]`, so setting `_primary_service_id = selected_icp` above makes it stick. Add `from .const import ..., CONF_ICP` to the imports.

**Why**: single cascade point — filtering the list + fixing primary is all that's needed; importer loop (337-344) and `sensor.py:69` naturally follow the filtered list.

### Step 4: Reload when the option changes

**File**: `custom_components/mercury_co_nz/__init__.py`  •  **Action**: UPDATE (in `async_setup_entry`, before `return True` at 104)
```python
entry.async_on_unload(entry.add_update_listener(_async_options_updated))
...

async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload so `_discover_icps_if_needed` re-runs with the new pinned ICP."""
    await hass.config_entries.async_reload(entry.entry_id)
```
**Why**: options changes must rebuild the coordinator (fresh `self._discovered = False`) so discovery re-applies the filter and entities are recreated.

### Step 5: Tests

**File**: `custom_components/mercury_co_nz/tests/test_multi_icp.py`  •  **Action**: UPDATE (append)

Mirror the existing multi-ICP test fixtures. Add cases:
```python
async def test_pinned_icp_filters_discovery_to_one(...):
    # entry.options = {CONF_ICP: "<secondary_service_id>"}; after discovery:
    #   coordinator._discovered_electricity_services == [that one service]
    #   coordinator._primary_service_id == "<secondary_service_id>"

async def test_pinned_icp_makes_account_scoped_sensors_read_that_icp(...):
    # monthly_/weekly_ top-level keys come from the pinned ICP's per-service slice

async def test_pinned_icp_absent_falls_back_to_all(...):
    # options CONF_ICP = "does-not-exist" → warning logged, all ICPs kept

async def test_no_pinned_icp_is_unchanged_v200_behavior(...):
    # options empty → all ICPs discovered, primary == services[0]
```

### Step 6: Version bump

**File**: `manifest.json` → `"version": "2.1.0"` (additive feature; options are backward-compatible, no migration needed).

---

## Patterns to Follow

- OptionsFlow: standard HA pattern (`async_get_options_flow` + `OptionsFlow` subclass) — mirror the existing `async_show_form`/`vol.Schema` style already in `config_flow.py:73-96`.
- Reading discovered ICPs: the coordinator exposes `_discovered_electricity_services` and `_primary_service_id` (used at `sensor.py:69-70`); reuse the same attributes.
- Tests: mirror `test_multi_icp.py`'s existing `test_primary_*` fixtures and coordinator-construction helpers.

---

## Edge Cases & Risks

| Risk / Edge case | Mitigation |
| --- | --- |
| Options flow opened before first discovery (no ICP list) | `async_abort(reason="icps_not_discovered")` with a translation string telling the user to wait for the first poll. |
| Pinned `service_id` no longer on the account | Warning + fall back to all ICPs (Step 3 `else`). |
| `bill_*` sensors are account-level (one bill covers all ICPs) | Cannot be split — Mercury returns one bill per account. Document that bill/amount-due stay account-wide even when an ICP is pinned. |
| User changes the pin mid-life on one instance | Pinned ICP becomes primary → writes to the legacy account-based `statistic_id`, causing a data discontinuity vs the previously-primary ICP. Note in the options description; acceptable for the intended fresh-per-instance setup. |
| Gas services on a pinned instance | Option scopes **electricity** ICPs only; gas (usually one service) is left as-is. Note as out-of-scope for v1 of this feature. |
| Existing single-instance multi-ICP users | Option defaults to unset → identical v2.0.0 behavior; no regression. |

---

## Validation

### Automated
```bash
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/ -q
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/test_multi_icp.py -q
```

### Manual
1. On a multi-ICP account: Settings → Devices & Services → Mercury → **Configure** → pick an ICP → Submit. Integration reloads.
2. Confirm only the pinned ICP's device/entities exist; other ICP devices are gone.
3. Confirm `monthly_*`/`weekly_*` summary sensors and the usage charts now show the pinned ICP's data (not combined/primary).
4. Clear the option (choose "All ICPs") → reload → all ICP devices reappear (v2.0.0 behavior).

---

## Scope Boundaries

**IN SCOPE:**
- OptionsFlow to pin one **electricity** ICP per instance; scope discovery, entities, account-scoped summaries, and charts to it.
- Reload on option change; sensible fallback + tests; version → 2.1.0.

**OUT OF SCOPE (do not touch):**
- Splitting `bill_*`/account-level data per ICP (Mercury serves one bill per account).
- Per-ICP gas scoping (electricity-only for this iteration).
- The multi-ICP data-fetch architecture itself (already shipped in v2.0.0; this only adds a selection/filter layer).
- Any change to primary-ICP statistics back-compat for unset (default) installs.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-07-20
- **Artifact**: `.claude/PRPs/issues/issue-30.md`
