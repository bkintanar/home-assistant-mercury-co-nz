# Feature: Gas Monthly Summary Card (bar chart with month nav)

## Summary

Build a new LitElement Lovelace card — `mercury-gas-monthly-summary-card` — that mirrors the **monthly mode of the existing `energy-usage-card.js`** (the bar-chart with prev/next pagination), but reads from gas-side data and renders each bar with a color that reflects its `is_estimated` flag (yellow `rgb(255, 240, 0)` for actual readings, gray `#727272` for estimated). Also adds the missing Python plumbing — currently `gas_monthly_usage_history` lives in `coordinator.data` but is **not exposed on any sensor entity**, so a new chart-capable gas sensor type must be added so the card has an entity to read.

## User Story

As a Mercury Energy NZ customer with both electricity and gas
I want a monthly bar-chart dashboard widget for gas consumption with the same UX as the existing electricity usage card
So that I can see my month-by-month gas usage and immediately tell which periods are actual meter reads vs Mercury estimates.

## Problem Statement

The integration already exposes a beautiful electricity bar-chart card (`energy-usage-card.js`, monthly mode) reading `entity.attributes.monthly_usage_history`. There is **no equivalent for gas**: `gas_monthly_usage_history` is computed (post-v1.5.2 via pymercury 1.1.3 `consumption_periods` or local `_collapse_gas_pairs`), pushed into `coordinator.data` with `gas_` prefix, and consumed by the statistics importer for the Energy Dashboard — but never surfaced as a sensor `extra_state_attributes` entry, so frontend cards cannot read it. Additionally, no card in this codebase visually distinguishes estimated vs actual reads, even though gas billing pairs include both.

## Solution Statement

Two coordinated changes:

1. **Python: expose gas chart data on a sensor.** Add a new `gas_monthly_usage` sensor type to `SENSOR_TYPES` (kWh-denominated total_usage scalar), and extend `MercurySensor.extra_state_attributes` to populate `gas_monthly_usage_history` (the pre-collapsed per-period list including `is_estimated` and `read_type`) on this new sensor. Mirror the existing electricity chart pattern at `sensor.py:267-321`.
2. **JS: clone & specialize the bar-chart card.** Create `gas-monthly-summary-card.js` extending the same LitElement / `mercuryLitCore` mixin pattern as `energy-usage-card.js`. Strip down to monthly-only (no period-tab switcher needed; gas only has monthly data). Read `entity.attributes.gas_monthly_usage_history`. Use Chart.js's per-bar `backgroundColor`/`borderColor` array support to colorize each bar based on `entry.is_estimated`. Register the new file in `ALLOWED_JS_FILES` (`__init__.py`) and `JSMODULES` (`const.py`) so it loads via `frontend/__init__.py`.

## Metadata

| Field            | Value                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------ |
| Type             | NEW_CAPABILITY                                                                                                     |
| Complexity       | MEDIUM                                                                                                             |
| Systems Affected | sensor.py (new sensor type + chart attributes), const.py (sensor type + JSMODULES), __init__.py (ALLOWED_JS_FILES), new gas-monthly-summary-card.js |
| Dependencies     | LitElement 3.1.0 (already loaded), Chart.js 4.5.0 (already loaded via CDN in core.js), pymercury>=1.1.3 (already pinned in manifest)              |
| Estimated Tasks  | 7                                                                                                                  |

---

## UX Design

### Before State
```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                              BEFORE STATE                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                                ║
║  USER's Lovelace dashboard:                                                    ║
║                                                                                ║
║   ┌──────────────────────────────────────────────────────┐                     ║
║   │ Mercury Energy Usage Card (electricity only)         │                     ║
║   │  [Hourly] [Daily] [Monthly]                          │                     ║
║   │  ┌────────────────────────────────────┐              │                     ║
║   │  │  ▓ ▓ ▓ ▓ ▓ ▓  (yellow bars)        │              │                     ║
║   │  │ Jan Feb Mar Apr May Jun            │              │                     ║
║   │  └────────────────────────────────────┘              │                     ║
║   │   <  1 Mar – 27 Mar  >                               │                     ║
║   └──────────────────────────────────────────────────────┘                     ║
║                                                                                ║
║   ┌──────────────────────────────────────────────────────┐                     ║
║   │ HA Energy Dashboard "Gas" section                    │                     ║
║   │  bars-only, no nav, no estimate/actual tag           │                     ║
║   └──────────────────────────────────────────────────────┘                     ║
║                                                                                ║
║  USER_FLOW: Electricity has rich chart card. Gas only appears as an Energy     ║
║   Dashboard summary bar — no in-card month nav, no estimate/actual indicator,  ║
║   no per-period cost tooltip.                                                  ║
║  PAIN_POINT: User cannot see gas history with the same depth as electricity.   ║
║   Cannot tell at a glance whether the monthly value was a real meter read or  ║
║   an estimate.                                                                 ║
║  DATA_FLOW: gas_monthly_usage_history → combined_data → statistics importer    ║
║   ONLY. Never reaches sensor.extra_state_attributes, so no JS card can read it.║
║                                                                                ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### After State
```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                               AFTER STATE                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                                ║
║  USER's Lovelace dashboard:                                                    ║
║                                                                                ║
║   ┌──────────────────────────────────────────────────────┐                     ║
║   │ Mercury Energy Usage Card (electricity)              │                     ║
║   │  [Hourly] [Daily] [Monthly]   ▓ ▓ ▓ ▓ ▓ ▓            │                     ║
║   └──────────────────────────────────────────────────────┘                     ║
║                                                                                ║
║   ┌──────────────────────────────────────────────────────┐  ◄── NEW CARD       ║
║   │ Mercury Gas Monthly Summary Card                     │                     ║
║   │  ┌────────────────────────────────────────┐          │                     ║
║   │  │  ░ ▓ ░ ▓ ░ ░ ▓ ░ ▓ ░  (mixed colors)   │          │                     ║
║   │  │ Jul Jul Aug Sep Oct Nov Dec Jan Feb Mar│          │                     ║
║   │  │  est act est act est est act est act est│          │                     ║
║   │  └────────────────────────────────────────┘          │                     ║
║   │   <  27 Feb – 27 Mar  >                              │                     ║
║   │   ● Actual  ○ Estimated   $156.28 | 460 kWh          │                     ║
║   └──────────────────────────────────────────────────────┘                     ║
║                                                                                ║
║   ▓ = yellow rgb(255,240,0) = actual meter read                                ║
║   ░ = gray  #727272         = Mercury estimate                                 ║
║                                                                                ║
║  USER_FLOW: User adds card via Lovelace UI (resource auto-registers via HACS); ║
║   sets `entity: sensor.mercury_nz_gas_monthly_usage`; chart renders ~10 bars   ║
║   one per billing period; clicking a bar shows the period's invoice range +   ║
║   $cost + kWh; prev/next arrows page back through history.                    ║
║  VALUE_ADD: Same depth of insight as electricity card. Visual estimate/actual ║
║   indicator (the first time this distinction is rendered anywhere in the     ║
║   integration's UI).                                                          ║
║  DATA_FLOW: gas_monthly.consumption_periods (pymercury 1.1.3) → coordinator   ║
║   gas_ prefix → sensor.gas_monthly_usage.extra_state_attributes               ║
║   .gas_monthly_usage_history → card reads via hass.states[entity_id]          ║
║   → Chart.js renders with per-bar backgroundColor array.                      ║
║                                                                                ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes

| Location                                             | Before                                    | After                                                                                    | User Impact                                                                            |
| ---------------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `sensor.mercury_nz_gas_monthly_usage`                | Does not exist                            | New sensor with kWh state and `gas_monthly_usage_history` attribute                      | Gas data becomes a first-class HA entity — usable in any card, automation, template    |
| Lovelace dashboard config UI                         | Only "Mercury Energy Usage Card" choice   | Adds "Mercury Gas Monthly Summary Card" in the custom-card picker                        | User can drop the card in via the UI                                                   |
| Card bar appearance                                  | (no card)                                 | Yellow bars for actual periods, gray bars for estimated periods                          | Visual call-out of which months Mercury actually read the meter vs estimated           |

---

## Mandatory Reading

**CRITICAL: Implementation agent MUST read these files before starting any task:**

| Priority | File                                                                              | Lines        | Why Read This                                                                                                     |
| -------- | --------------------------------------------------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------- |
| P0       | `custom_components/mercury_co_nz/energy-usage-card.js`                            | 1-1400       | THE mirror target — clone its monthly mode, navigation, click-to-select, Chart.js setup                          |
| P0       | `custom_components/mercury_co_nz/sensor.py`                                       | 245-340      | The `extra_state_attributes` pattern — chart data is gated on a sensor whitelist (CHART_DATA_SENSORS)            |
| P0       | `custom_components/mercury_co_nz/const.py`                                        | 18-22, 33-50, 167-172 | JSMODULES list, SENSOR_TYPES dict shape, the existing `bill_gas_amount` entry as a sample gas sensor          |
| P1       | `custom_components/mercury_co_nz/__init__.py`                                     | 23-58        | `ALLOWED_JS_FILES` whitelist + `MercuryStaticView` URL routing pattern                                           |
| P1       | `custom_components/mercury_co_nz/core.js`                                         | 1-430        | `mercuryLitCore` mixin — what `initializeBase()` provides (CHART_COLORS, theme detection, `_loadChartJS`, etc.) |
| P1       | `custom_components/mercury_co_nz/styles.js`                                       | 584-614      | `mercuryChartStyles` (combined export for chart cards) and `mercuryColors` palette including SECONDARY_GRAY      |
| P1       | `custom_components/mercury_co_nz/mercury_api.py`                                  | 977-1059     | `get_gas_usage_data()` — confirms what's in `gas_monthly_usage_history`, including the consumption_periods path  |
| P1       | `custom_components/mercury_co_nz/coordinator.py`                                  | 169-176      | The `gas_` prefix loop that creates `combined_data["gas_monthly_usage_history"]`                                 |
| P2       | `custom_components/mercury_co_nz/energy-weekly-summary-card.js`                   | 1-200        | Reference for stripped-down chart card (single period mode) — but our new card mirrors usage-card more closely  |
| P2       | `custom_components/mercury_co_nz/frontend/__init__.py`                            | 60-110       | How `JSMODULES` entries become Lovelace resources (`async_create_item`)                                          |
| P2       | `/var/www/personal/pymercury/pymercury/api/models/base.py`                        | 197-287      | Authoritative `daily_usage` shape (8 keys incl. `is_estimated`) and `consumption_periods` property               |

**External Documentation:**

| Source                                                                                                              | Section                                | Why Needed                                                                                            |
| ------------------------------------------------------------------------------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [Chart.js v4.5 docs](https://www.chartjs.org/docs/4.5.0/charts/bar.html#data-structure)                             | "Data Structure" / "Bar Chart"         | Confirm per-bar coloring via `backgroundColor: [color1, color2, ...]` array (one entry per data point) |
| [Chart.js v4.5 dataset config](https://www.chartjs.org/docs/4.5.0/general/colors.html)                              | "Per-bar colors"                       | Same — used to vary actual/estimate                                                                    |
| [LitElement 3.1.0 docs](https://lit.dev/docs/v3/components/lifecycle/#updated)                                     | "updated" lifecycle                    | Pattern already used in `energy-usage-card.js` for chart re-rendering on hass updates                 |

(No new external dependencies — Chart.js is loaded from CDN by `core.js:_loadChartJS` and LitElement is imported via the same `unpkg.com/lit@3.1.0/index.js?module` URL all existing cards use.)

---

## Patterns to Mirror

**SENSOR_TYPES_ENTRY:**
```python
# SOURCE: custom_components/mercury_co_nz/const.py:167-173
# COPY THIS PATTERN (gas already has bill_gas_amount; mirror the shape):
"bill_gas_amount": {
    "name": "Gas Amount",
    "unit": "$",
    "icon": "mdi:fire",
    "device_class": "monetary",
    "state_class": "total",
},
```

**CHART_DATA_SENSORS_PATTERN:**
```python
# SOURCE: custom_components/mercury_co_nz/sensor.py:255-267
# COPY THIS PATTERN — and add the new gas sensor to it:
CHART_DATA_SENSORS = [
    "energy_usage",      # Main energy usage sensor - primary chart sensor
    "total_usage",       # Total usage sensor
    "current_bill"       # Current bill sensor
]

if self._sensor_type in CHART_DATA_SENSORS:
    # ... daily/hourly/monthly_usage_history population ...
```

**MONTHLY_USAGE_HISTORY_ATTRIBUTE_BLOCK:**
```python
# SOURCE: custom_components/mercury_co_nz/sensor.py:317-321
# COPY THIS EXACT PATTERN for the gas variant:
if "monthly_usage_history" in self.coordinator.data:
    monthly_history = self.coordinator.data["monthly_usage_history"]
    attributes["monthly_usage_history"] = monthly_history
    attributes["monthly_data_points"] = len(monthly_history)
```

**JSMODULES_REGISTRATION:**
```python
# SOURCE: custom_components/mercury_co_nz/const.py:18-22
# COPY THIS PATTERN — append the new card:
JSMODULES: Final[list[dict[str, str]]] = [
    {"name": "Mercury Energy Usage Card", "filename": "energy-usage-card.js", "version": INTEGRATION_VERSION},
    {"name": "Mercury Energy Weekly Summary Card", "filename": "energy-weekly-summary-card.js", "version": INTEGRATION_VERSION},
    {"name": "Mercury Energy Monthly Summary Card", "filename": "energy-monthly-summary-card.js", "version": INTEGRATION_VERSION},
]
```

**ALLOWED_JS_FILES_WHITELIST:**
```python
# SOURCE: custom_components/mercury_co_nz/__init__.py:23-29
# COPY THIS PATTERN — add the new filename:
ALLOWED_JS_FILES = frozenset({
    "core.js",
    "styles.js",
    "energy-usage-card.js",
    "energy-weekly-summary-card.js",
    "energy-monthly-summary-card.js",
})
```

**LITELEMENT_CARD_HEADER (top of every card file):**
```javascript
// SOURCE: custom_components/mercury_co_nz/energy-usage-card.js:1-7
// COPY THIS EXACTLY:
import { LitElement, html, css } from 'https://unpkg.com/lit@3.1.0/index.js?module';
import { mercuryChartStyles, mercuryColors } from './styles.js';
import { mercuryLitCore } from './core.js';

class MercuryEnergyUsageCard extends LitElement {
```

**LITELEMENT_CARD_INIT (mixin composition):**
```javascript
// SOURCE: custom_components/mercury_co_nz/energy-usage-card.js:32-50
// COPY THIS PATTERN — adapted for gas:
constructor() {
  super();
  this.config = {};
  this._currentPage = 0;
  this._selectedDate = null;
  this.itemsPerPage = 6;            // visible bar count per "page"
  Object.assign(this, mercuryLitCore);
  this.initializeBase();
  this.CHART_COLORS = { ...this.CHART_COLORS, ...mercuryColors };
}
```

**STATIC_PROPERTIES:**
```javascript
// SOURCE: custom_components/mercury_co_nz/energy-monthly-summary-card.js:26-30
// COPY THIS PATTERN:
static properties = {
  hass: { type: Object },
  config: { type: Object },
  _entity: { type: Object, state: true }
};
```

**CHART_DATASET_PER_BAR_COLOR (the new bit — Chart.js supports color-arrays):**
```javascript
// PATTERN (NEW — derived from Chart.js v4 docs and the existing single-color pattern):
// SOURCE FOR REFERENCE: custom_components/mercury_co_nz/energy-usage-card.js:363-384
// (the existing monthly bar chart uses single-color backgroundColor; we extend to array)

const barColors = paddedPageData.map(item =>
  item.consumption === 0 || item.date == null
    ? this.CHART_COLORS.PRIMARY_YELLOW          // unused/empty pad bars (will be hidden by zero height anyway)
    : item.is_estimated
      ? this.CHART_COLORS.SECONDARY_GRAY        // '#727272' — estimated read
      : this.CHART_COLORS.PRIMARY_YELLOW        // 'rgb(255, 240, 0)' — actual read
);

return [{
  label: 'Gas Usage (kWh)',
  data: usageData,
  backgroundColor: barColors,                   // ARRAY — one per bar
  borderColor: barColors,
  borderWidth: 2,
  borderRadius: { topLeft: 3, topRight: 3, bottomLeft: 0, bottomRight: 0 },
  barPercentage: 0.9,
  type: 'bar',
  yAxisID: 'y',
  order: 1
}];
```

**NAVIGATION_HANDLER (monthly logic, copy verbatim):**
```javascript
// SOURCE: custom_components/mercury_co_nz/energy-usage-card.js:967-1008
// (copy the monthly branch — drop the daily/hourly branches in the new card)
_handleNavigation(direction) {
  // ... reads entity.attributes.gas_monthly_usage_history (was: monthly_usage_history)
  // ... pages by this._currentPage * this.itemsPerPage
  // ... no period switcher to coordinate (gas only has monthly)
}
```

**LEGEND_CIRCLE_CSS (existing — adapt to two circles):**
```css
/* SOURCE: custom_components/mercury_co_nz/styles.js:514-516 */
/* PATTERN — yellow circle exists; ADD a gray-circle modifier for the legend */
.legend-circle {
  background-color: rgb(255, 240, 0); /* PRIMARY_YELLOW — actual */
}
.legend-circle.estimated {
  background-color: #727272;          /* SECONDARY_GRAY — estimated */
}
```

**FRONTEND_URL_PATTERN:**
```python
# SOURCE: custom_components/mercury_co_nz/__init__.py:32-58
# Static-served via /api/mercury_co_nz/<filename>; new file slots in transparently.
class MercuryStaticView(HomeAssistantView):
    url = f"{URL_BASE}/{{filename:.+}}"   # URL_BASE = "/api/mercury_co_nz"
    requires_auth = False
```

**CONSOLE_BANNER (every card file ends with this):**
```javascript
// SOURCE: custom_components/mercury_co_nz/energy-monthly-summary-card.js:223-227
// COPY THIS PATTERN:
console.info(
  '%c MERCURY-GAS-MONTHLY-SUMMARY-CARD %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
```

---

## Files to Change

| File                                                                | Action | Justification                                                                          |
| ------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/const.py`                          | UPDATE | Add `gas_monthly_usage` to `SENSOR_TYPES`; add new card to `JSMODULES`                |
| `custom_components/mercury_co_nz/sensor.py`                         | UPDATE | Add `gas_monthly_usage` to `CHART_DATA_SENSORS`; populate `gas_monthly_usage_history` attribute on it |
| `custom_components/mercury_co_nz/__init__.py`                       | UPDATE | Add `gas-monthly-summary-card.js` to `ALLOWED_JS_FILES`                                |
| `custom_components/mercury_co_nz/gas-monthly-summary-card.js`       | CREATE | The new LitElement card (~600 LOC adapted from `energy-usage-card.js` monthly mode)    |
| `custom_components/mercury_co_nz/styles.js`                         | UPDATE | Add `.legend-circle.estimated { background-color: #727272 }` modifier                   |
| `custom_components/mercury_co_nz/manifest.json`                     | UPDATE | Bump version `1.5.2` → `1.6.0` (new minor — adds a feature)                            |
| `custom_components/mercury_co_nz/tests/test_attributes.py`          | UPDATE | Add a unit test asserting the new `gas_monthly_usage` sensor exposes `gas_monthly_usage_history` |

---

## NOT Building (Scope Limits)

Explicit exclusions to prevent scope creep:

- **Multi-ICP gas support on this card.** Main has single-gas-ICP only (per `mercury_api.get_gas_usage_data` which `break`s after the first gas service). Multi-ICP gas is on the `fix/multi-icp-v200-phases-2-5` branch — this plan ships on `main` and the v2.0.0 branch will get the card via cherry-pick + per-ICP entity multiplication separately.
- **Daily/hourly tabs.** Mercury's gas API only returns monthly data (confirmed by maintainer testing — see `mercury_api.py:980-984`). No period switcher — the card is monthly-only.
- **Cost projection / progress-bar features.** Those belong on a separate `gas-monthly-summary-card` companion if requested later. This plan is the bar-chart-with-nav card only.
- **A new electricity-vs-gas combined card.** Out of scope — keeping gas as a separate card matches the existing pattern.
- **Sensor-attribute size truncation for gas history.** Gas has ~10 entries × ~200 bytes ≈ 2KB — well under the 14KB HA recorder limit. No `[-CHART_ATTRIBUTE_DAILY_DAYS:]` truncation needed.
- **Backwards-compat for pymercury <1.1.3.** Manifest already pins `>=1.1.3` — `consumption_periods` is the primary path; the local `_collapse_gas_pairs` fallback in `mercury_api.py:1041` handles 1.1.2 defensively but `is_estimated` may be missing on those entries. Acceptable degradation: gray-vs-yellow falls back to all-yellow when `is_estimated` is undefined.
- **Tests for the JS card itself.** No frontend test infrastructure exists in this repo (verified — zero JS tests). The Python-side test at Task 7 covers the data plumbing.

---

## Step-by-Step Tasks

Execute in order. Each task is atomic and independently verifiable.

### Task 1: UPDATE `custom_components/mercury_co_nz/const.py` — add gas chart sensor type

- **ACTION**: ADD a new entry to `SENSOR_TYPES` and append a new module to `JSMODULES`
- **IMPLEMENT**:
  ```python
  # In SENSOR_TYPES (after "bill_gas_amount" or at end of bill section):
  "gas_monthly_usage": {
      "name": "Gas Monthly Usage",
      "unit": "kWh",
      "icon": "mdi:fire",
      "device_class": "energy",
      "state_class": "total_increasing",
  },
  ```
  ```python
  # In JSMODULES, append after the existing entries:
  {"name": "Mercury Gas Monthly Summary Card", "filename": "gas-monthly-summary-card.js", "version": INTEGRATION_VERSION},
  ```
- **MIRROR**: `const.py:160-166` (`bill_electricity_amount` shape) and `const.py:18-22` (existing `JSMODULES` entries)
- **GOTCHA**: Use `state_class: "total_increasing"` to match how electricity's chart sensor is registered. The unit "kWh" matches the gas billing surface (Mercury bills gas in kWh, not m³). `device_class: "energy"` makes the sensor available to the HA Energy Dashboard's gas section if the user wants to wire it up.
- **VALIDATE**: `.venv/bin/python -c "from custom_components.mercury_co_nz import const; assert 'gas_monthly_usage' in const.SENSOR_TYPES; assert any(m['filename'] == 'gas-monthly-summary-card.js' for m in const.JSMODULES); print('OK')"`

### Task 2: UPDATE `custom_components/mercury_co_nz/sensor.py` — wire up chart attributes

- **ACTION**: Add `gas_monthly_usage` to `CHART_DATA_SENSORS` AND add a gas branch in `extra_state_attributes` that copies `gas_monthly_usage_history` from `coordinator.data` onto the sensor
- **IMPLEMENT**:
  ```python
  # sensor.py:255-259 — extend the whitelist
  CHART_DATA_SENSORS = [
      "energy_usage",
      "total_usage",
      "current_bill",
      "gas_monthly_usage",   # NEW — gas chart sensor
  ]
  ```
  ```python
  # sensor.py — inside the existing `if self._sensor_type in CHART_DATA_SENSORS:` block,
  # AFTER the existing electricity monthly_usage_history block at line 321,
  # add a gas-specific block guarded on the sensor type:
  if self._sensor_type == "gas_monthly_usage":
      gas_history = self.coordinator.data.get("gas_monthly_usage_history") or []
      attributes["gas_monthly_usage_history"] = gas_history
      attributes["gas_monthly_data_points"] = len(gas_history)
      attributes["gas_monthly_total_usage"] = self.coordinator.data.get("gas_monthly_usage") or 0
      attributes["gas_monthly_total_cost"] = self.coordinator.data.get("gas_monthly_cost") or 0
  ```
- **MIRROR**: The exact electricity pattern at `sensor.py:317-321`. The gas-specific guard prevents leaking gas attributes onto electricity sensors (which would bloat their already-tight 14KB attribute budget — Issue #4 territory).
- **GOTCHA**: Don't add the gas attributes to the OUTER (non-CHART) attribute block at `sensor.py:325-340` — that block runs for every sensor and would balloon attribute size on `bill_*` sensors that don't need chart data.
- **VALIDATE**: `.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/test_attributes.py -v --no-cov`

### Task 3: UPDATE `custom_components/mercury_co_nz/__init__.py` — whitelist the new file

- **ACTION**: Add `"gas-monthly-summary-card.js"` to the `ALLOWED_JS_FILES` frozenset
- **IMPLEMENT**:
  ```python
  # __init__.py:23-29 — extend the frozenset
  ALLOWED_JS_FILES = frozenset({
      "core.js",
      "styles.js",
      "energy-usage-card.js",
      "energy-weekly-summary-card.js",
      "energy-monthly-summary-card.js",
      "gas-monthly-summary-card.js",   # NEW
  })
  ```
- **MIRROR**: `__init__.py:23-29`
- **GOTCHA**: The `MercuryStaticView` returns 404 for any filename NOT in this set. Forgetting this entry produces a confusing "card not found" failure with no Python-side error.
- **VALIDATE**: `.venv/bin/python -c "from custom_components.mercury_co_nz import ALLOWED_JS_FILES; assert 'gas-monthly-summary-card.js' in ALLOWED_JS_FILES; print('OK')"`

### Task 4: CREATE `custom_components/mercury_co_nz/gas-monthly-summary-card.js`

- **ACTION**: CREATE the new LitElement card file by adapting the monthly-mode of `energy-usage-card.js`
- **IMPLEMENT**: The card is a stripped-down clone of `energy-usage-card.js` with these specific differences:
  1. **Header / class name / customElement registration:**
     ```javascript
     import { LitElement, html, css } from 'https://unpkg.com/lit@3.1.0/index.js?module';
     import { mercuryChartStyles, mercuryColors } from './styles.js';
     import { mercuryLitCore } from './core.js';

     class MercuryGasMonthlySummaryCard extends LitElement {
       static styles = mercuryChartStyles;
       static properties = {
         hass: { type: Object },
         config: { type: Object },
         _entity: { type: Object, state: true }
       };
       // ... constructor with mercuryLitCore mixin (mirror energy-usage-card.js:32-50) ...
     }

     if (!customElements.get('mercury-gas-monthly-summary-card')) {
       customElements.define('mercury-gas-monthly-summary-card', MercuryGasMonthlySummaryCard);
     }

     window.customCards = window.customCards || [];
     window.customCards.push({
       type: 'mercury-gas-monthly-summary-card',
       name: 'Mercury Gas Monthly Summary Card',
       description: 'Monthly gas consumption bar chart for Mercury Energy NZ',
       preview: false,
       documentationURL: 'https://github.com/bkintanar/this-repo'
     });
     ```
  2. **No period switcher.** Hard-code `_currentPeriod = 'monthly'`. Drop the `_renderPeriodTabs()` call.
  3. **Data source attribute change:** every reference to `entity.attributes.monthly_usage_history` in `energy-usage-card.js` becomes `entity.attributes.gas_monthly_usage_history` in this card. Apply globally — there are ~5 such references (lines 425, 968, 1118, 1163, 1180 in the original).
  4. **Per-bar coloring (the key new logic):**
     ```javascript
     // In _getDatasetsForPeriod() — use a color array instead of a single string:
     const barColors = paddedPageData.map(item =>
       item.is_estimated === true
         ? this.CHART_COLORS.SECONDARY_GRAY     // '#727272'
         : this.CHART_COLORS.PRIMARY_YELLOW     // 'rgb(255, 240, 0)'
     );

     return [{
       label: 'Gas Usage (kWh)',
       data: usageData,
       backgroundColor: barColors,
       borderColor: barColors,
       borderWidth: 2,
       borderRadius: { topLeft: 3, topRight: 3, bottomLeft: 0, bottomRight: 0 },
       barPercentage: 0.9,
       type: 'bar',
       yAxisID: 'y',
       order: 1
     }];
     ```
  5. **Legend (two entries instead of one):**
     ```javascript
     _renderChartLegend() {
       return html`
         <div class="chart-legend">
           <div class="legend-item">
             <span class="legend-circle"></span>
             <span class="legend-label">Actual</span>
           </div>
           <div class="legend-item">
             <span class="legend-circle estimated"></span>
             <span class="legend-label">Estimated</span>
           </div>
         </div>
       `;
     }
     ```
  6. **Tooltip / info-box label:** "Your gas usage for this billing period" (instead of electricity wording).
  7. **No temperature dataset.** The electricity card has a temperature line overlay (`_getDatasetsForPeriod` second dataset). Drop it for gas — gas data has no temperature axis.
  8. **Console banner at end of file:**
     ```javascript
     console.info(
       '%c MERCURY-GAS-MONTHLY-SUMMARY-CARD %c v1.0.0 ',
       'color: orange; font-weight: bold; background: black',
       'color: white; font-weight: bold; background: dimgray'
     );
     ```
- **MIRROR**: `custom_components/mercury_co_nz/energy-usage-card.js` lines 1-7 (header), 32-50 (constructor), 363-384 (monthly dataset config), 425-430 (data source read), 561-585 (label/padding), 967-1008 (navigation), 1117-1124 (nav-disabled bounds), 1161-1197 (nav description), 1274-1286 (info box), 1312-1339 (nav render), 1342-1367 (legend)
- **GOTCHA 1**: Chart.js dataset config requires `backgroundColor` to be EITHER a single string OR an array of strings with `data.length` matching exactly. If the array length and data length disagree, Chart.js silently falls back to its default palette. Always derive `barColors` from `paddedPageData` (post-padding) so the array is the same length as the data array.
- **GOTCHA 2**: `entry.is_estimated` may be `undefined` if pymercury 1.1.2 was somehow installed (despite the `>=1.1.3` pin) and the local `_collapse_gas_pairs` fallback fed entries without that key. Use `item.is_estimated === true` (strict comparison) so undefined falls into the actual/yellow path — visible degradation rather than hidden bug.
- **GOTCHA 3**: When the user clicks a bar, the info panel should also show the read type. Add a small "(estimated)" annotation:
  ```javascript
  ${this._selectedDate.is_estimated ? html`<span class="estimate-tag">(estimated)</span>` : ''}
  ```
- **VALIDATE**:
  - File loads without JS error: `node -e "require('fs').readFileSync('custom_components/mercury_co_nz/gas-monthly-summary-card.js', 'utf8')"` (sanity read)
  - File served by static view: after restart, browser fetch of `http://homeassistant.local:8123/api/mercury_co_nz/gas-monthly-summary-card.js` returns 200 with the JS body
  - Lovelace UI shows "Mercury Gas Monthly Summary Card" in the card-picker

### Task 5: UPDATE `custom_components/mercury_co_nz/styles.js` — add the gray-circle modifier

- **ACTION**: Add a `.legend-circle.estimated` rule after the existing `.legend-circle` definition
- **IMPLEMENT**:
  ```css
  /* In styles.js around line 514-516, ADD: */
  .legend-circle.estimated {
    background-color: #727272;  /* SECONDARY_GRAY */
  }
  ```
- **MIRROR**: `styles.js:514-516` (the existing `.legend-circle` rule sits inside `chartLegendStyles` exported as part of `mercuryChartStyles`)
- **GOTCHA**: `styles.js` is a JS file using `css` template literals from `lit`. Add the rule inside the same `css\`...\`` block where `.legend-circle` already lives, not as a standalone export.
- **VALIDATE**: visual check after browser reload — the second legend item ("Estimated") shows a gray circle.

### Task 6: UPDATE `custom_components/mercury_co_nz/manifest.json` — version bump

- **ACTION**: Bump version `1.5.2` → `1.6.0` (minor — new feature)
- **IMPLEMENT**:
  ```json
  "version": "1.6.0"
  ```
- **MIRROR**: Existing `manifest.json` shape (line 13)
- **GOTCHA**: HACS surfaces the update prompt only when this version increments. The `JSMODULES` entries also use `INTEGRATION_VERSION` (= manifest version) as a query string — bumping invalidates the browser cache for ALL cards in this integration, which is desired here so users get the new card without manual hard-refresh.
- **VALIDATE**: `python3 -c "import json; m=json.load(open('custom_components/mercury_co_nz/manifest.json')); assert m['version']=='1.6.0'; print('OK')"`

### Task 7: UPDATE `custom_components/mercury_co_nz/tests/test_attributes.py` — assert the new attribute path

- **ACTION**: Add a test that constructs a `MercurySensor` with type `"gas_monthly_usage"`, populates `coordinator.data["gas_monthly_usage_history"]` with a sample list, and asserts `extra_state_attributes` includes the chart-ready key
- **IMPLEMENT**:
  ```python
  # Append to test_attributes.py:

  def test_gas_monthly_usage_sensor_exposes_chart_history(coordinator_with_data):
      """gas_monthly_usage sensor must expose gas_monthly_usage_history as an
      extra_state_attribute so the gas-monthly-summary-card.js can read it via
      hass.states[entity_id].attributes.gas_monthly_usage_history.
      """
      sample_history = [
          {"date": "2026-02-26", "consumption": 397.0, "cost": 139.20,
           "invoice_from": "2026-01-31", "invoice_to": "2026-02-26",
           "is_estimated": True, "read_type": "estimate", "free_power": False},
          {"date": "2026-03-27", "consumption": 460.0, "cost": 156.28,
           "invoice_from": "2026-02-27", "invoice_to": "2026-03-27",
           "is_estimated": False, "read_type": "actual", "free_power": False},
      ]
      coordinator_with_data.data["gas_monthly_usage_history"] = sample_history
      coordinator_with_data.data["gas_monthly_usage"] = 4842.0
      coordinator_with_data.data["gas_monthly_cost"] = 1499.42

      from custom_components.mercury_co_nz.sensor import MercurySensor
      sensor = MercurySensor(
          coordinator_with_data, "gas_monthly_usage", "Mercury NZ", "user@example.com"
      )

      attrs = sensor.extra_state_attributes
      assert attrs["gas_monthly_usage_history"] == sample_history
      assert attrs["gas_monthly_data_points"] == 2
      assert attrs["gas_monthly_total_usage"] == 4842.0
      assert attrs["gas_monthly_total_cost"] == 1499.42
      # Critical for the card's per-bar coloring:
      assert attrs["gas_monthly_usage_history"][0]["is_estimated"] is True
      assert attrs["gas_monthly_usage_history"][1]["is_estimated"] is False


  def test_electricity_sensors_do_NOT_get_gas_attributes(coordinator_with_data):
      """Issue #4 guard: gas attributes must not bleed onto electricity chart
      sensors — they're already at attribute-size limit."""
      coordinator_with_data.data["gas_monthly_usage_history"] = [{"date": "2026-03-27"}]

      from custom_components.mercury_co_nz.sensor import MercurySensor
      sensor = MercurySensor(
          coordinator_with_data, "energy_usage", "Mercury NZ", "user@example.com"
      )

      attrs = sensor.extra_state_attributes
      assert "gas_monthly_usage_history" not in attrs
  ```
- **MIRROR**: existing `test_attributes.py` test patterns and fixtures
- **GOTCHA**: If a `coordinator_with_data` fixture doesn't exist, mirror the construction style from `tests/test_gas_pipeline.py:33-44` (`MagicMock`-based hass + a coordinator stub).
- **VALIDATE**: `.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/test_attributes.py -v --no-cov`

---

## Testing Strategy

### Unit Tests to Write

| Test File                                                   | Test Cases                                                                                        | Validates                                          |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| `custom_components/mercury_co_nz/tests/test_attributes.py` | `test_gas_monthly_usage_sensor_exposes_chart_history`, `test_electricity_sensors_do_NOT_get_gas_attributes` | Sensor attribute population + Issue #4 isolation |

### Edge Cases Checklist

- [ ] Empty `gas_monthly_usage_history` (no gas data ever fetched) → card renders empty/loading state, no JS error
- [ ] `gas_monthly_usage_history` with all `is_estimated: true` entries → chart shows all gray bars; legend still shows both entries
- [ ] `gas_monthly_usage_history` with all `is_estimated: false` → all yellow; matches existing electricity look
- [ ] `is_estimated` undefined on entries (pymercury 1.1.2 fallback) → defaults to yellow (actual)
- [ ] Single billing period (1 entry) → bar renders, prev arrow disabled, next arrow disabled
- [ ] Exactly `itemsPerPage` (6) entries → renders one full page, both arrows disabled
- [ ] More than `itemsPerPage` entries (typical: 10) → first page shows 6 most recent; prev arrow enabled
- [ ] User clicks empty-pad bar (zero consumption) → info panel handles gracefully (mirror existing card's behavior)
- [ ] Theme switch (light ↔ dark) mid-session → bar colors stay correct (yellow + gray are theme-independent)

---

## Validation Commands

### Level 1: STATIC_ANALYSIS

```bash
.venv/bin/python -c "
import ast
for p in [
    'custom_components/mercury_co_nz/sensor.py',
    'custom_components/mercury_co_nz/const.py',
    'custom_components/mercury_co_nz/__init__.py',
]:
    ast.parse(open(p).read())
    print(f'OK {p}')
"
node --check custom_components/mercury_co_nz/gas-monthly-summary-card.js && echo "JS OK"
```

**EXPECT**: Exit 0, all files report OK.

### Level 2: UNIT_TESTS

```bash
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/ --no-cov -q
```

**EXPECT**: All previously-passing tests still pass (103 on main pre-change), plus 2 new tests added in Task 7. Total ≥ 105/105 passing.

### Level 3: FULL_SUITE

```bash
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/ --no-cov -q && \
python3 -c "import json; m=json.load(open('custom_components/mercury_co_nz/manifest.json')); print('manifest version:', m['version'])"
```

**EXPECT**: tests pass, manifest reads `1.6.0`.

### Level 4: DATABASE_VALIDATION

Not applicable — no schema changes (HA recorder schema is owned by HA core).

### Level 5: BROWSER_VALIDATION (manual on a test HA instance)

After deploying and restarting HA fully:

- [ ] `sensor.mercury_nz_gas_monthly_usage` appears in **Developer Tools → States**
- [ ] Its state shows the gas total kWh and `unit_of_measurement: kWh`
- [ ] Its `attributes.gas_monthly_usage_history` is a list of ~10 dicts each containing `is_estimated` (true/false), `consumption`, `cost`, `invoice_from`, `invoice_to`
- [ ] Lovelace card-picker (Settings → Dashboards → Edit → Add Card → Custom) shows "Mercury Gas Monthly Summary Card"
- [ ] After adding the card with `entity: sensor.mercury_nz_gas_monthly_usage`:
  - [ ] Bars render
  - [ ] Months with `is_estimated: true` appear gray
  - [ ] Months with `is_estimated: false` appear yellow
  - [ ] Prev/next arrows page correctly
  - [ ] Clicking a bar shows the period's invoice range, $cost, kWh
  - [ ] Legend shows both "Actual" (yellow circle) and "Estimated" (gray circle)
  - [ ] HACS shows v1.6.0 update prompt for any user upgrading from v1.5.2
- [ ] Browser DevTools → Network: card JS file fetched as `200` from `/api/mercury_co_nz/gas-monthly-summary-card.js?v=1.6.0`

### Level 6: MANUAL_VALIDATION

1. Restart HA fully (not just reload integration — HACS-installed JS modules need full restart).
2. Verify the new sensor entity appears in Developer Tools → States.
3. Edit a Lovelace dashboard, add the new card, point it at `sensor.mercury_nz_gas_monthly_usage`.
4. Compare visual output against the existing electricity card's monthly mode — same look and feel, plus the gray-bar variation.
5. Cross-check a known estimated month against your actual Mercury bill to confirm the gray bar marks an estimate.

---

## Acceptance Criteria

- [ ] New `sensor.mercury_nz_gas_monthly_usage` entity appears in HA after restart
- [ ] Entity exposes `gas_monthly_usage_history` (list of ~10 dicts, each including `is_estimated` bool)
- [ ] New `mercury-gas-monthly-summary-card` registered as a custom card; appears in Lovelace's card-picker
- [ ] Card renders a bar chart with one bar per billing period
- [ ] Yellow bars for actual reads (`is_estimated: false`); gray bars for estimates (`is_estimated: true`)
- [ ] Prev/next month nav works (mirroring electricity card behavior)
- [ ] Clicking a bar shows that period's invoice range, cost, kWh, and an "(estimated)" tag if applicable
- [ ] Legend shows both "Actual" and "Estimated" with the right circle colors
- [ ] No regressions in existing 103 Python tests
- [ ] Existing electricity sensors do NOT have gas attributes added (Issue #4 size-budget guard preserved)
- [ ] HACS shows `v1.6.0` upgrade prompt to existing v1.5.2 users

---

## Completion Checklist

- [ ] Task 1: const.py updated (SENSOR_TYPES + JSMODULES)
- [ ] Task 2: sensor.py updated (CHART_DATA_SENSORS + gas attribute block)
- [ ] Task 3: __init__.py updated (ALLOWED_JS_FILES)
- [ ] Task 4: gas-monthly-summary-card.js created
- [ ] Task 5: styles.js updated (.legend-circle.estimated)
- [ ] Task 6: manifest.json bumped to 1.6.0
- [ ] Task 7: test_attributes.py extended with 2 new tests
- [ ] Level 1 static analysis passes
- [ ] Level 2 unit tests pass (≥105/105)
- [ ] Level 3 full suite + manifest check passes
- [ ] Level 5 browser validation completed on a test HA instance
- [ ] All acceptance criteria met

---

## Risks and Mitigations

| Risk                                                                                     | Likelihood | Impact | Mitigation                                                                                                                                                                                                  |
| ---------------------------------------------------------------------------------------- | ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `is_estimated` missing from entries because pymercury <1.1.3 is somehow installed        | LOW        | LOW    | Strict comparison `item.is_estimated === true` falls into yellow/actual path on undefined — visible degradation (everything yellow), not silent error. Manifest pin `>=1.1.3` enforced by HA pip resolution. |
| Chart.js per-bar `backgroundColor` array silently falls back to default if length mismatch | MEDIUM     | LOW    | Always derive `barColors` from the post-padding `paddedPageData`. Explicit unit test in card's render path comparing array lengths. Console-warn if mismatch detected (defensive guard).                    |
| Adding `gas_monthly_usage` to `CHART_DATA_SENSORS` accidentally also gives it electricity history attributes | LOW | MED | The gas-attribute block is specifically guarded `if self._sensor_type == "gas_monthly_usage":`. The electricity blocks are also implicit-typed (they read `daily_usage_history` keys that don't exist for gas data). Test 7 (`test_electricity_sensors_do_NOT_get_gas_attributes`) is the load-bearing assertion. |
| Sensor attribute size grows past 14KB                                                    | LOW        | LOW    | Gas has ~10 entries × ~250 bytes ≈ 2.5KB. Order of magnitude under the limit. No truncation needed. Test on real production data once deployed.                                                            |
| HACS-installed users don't see the new card without HA restart                           | MEDIUM     | LOW    | Document in README; mirror the v1.5.2 PR's migration note ("Settings → System → Restart Home Assistant"). Version bump to 1.6.0 invalidates browser cache via the `?v=1.6.0` query param on JS resource URL. |
| User has gas service but `gas_monthly_usage_history` is empty (Mercury returned no data) | MEDIUM     | LOW    | Card renders the existing loading-state path. Same UX as electricity card pre-data. No new error path needed.                                                                                              |
| New sensor accidentally breaks the v2.0.0 multi-ICP cherry-pick                          | MEDIUM     | MED    | The v2.0.0 branch has its own gas data path (per-ICP keys). Cherry-picking this card's commit will conflict on `sensor.py` and `mercury_api.py`. Resolution: re-implement the gas-history attribute population per-ICP on v2.0.0; the card itself (JS file) cherry-picks cleanly. Document in PR description.    |

---

## Notes

**Why a separate card (not a tab on the existing electricity card?):**

The electricity card has its monthly mode tightly integrated with hourly/daily — they share period-tab state, navigation history, and a temperature overlay. Folding gas in as a fourth tab would either: (a) require runtime branching on which fuel is currently selected and toggling temperature/coloring conditionally, doubling the card's logic surface; or (b) force a "fuel selector" on top of the period selector, which is a worse UX. A separate card mirrors the existing pattern (`energy-usage-card.js` is one card, `energy-weekly-summary-card.js` is another, `energy-monthly-summary-card.js` is a third) and keeps gas's monthly-only nature explicit in the card's name and shape.

**Why `device_class: "energy"` on the gas sensor:**

Even though Mercury bills gas in kWh equivalent, classifying as `energy` makes the new sensor compatible with HA's Energy Dashboard "Gas" section if the user wants to wire it up directly (vs. the existing statistics-importer-driven path). Consistent with electricity's chart sensor classification.

**Why no daily/hourly tabs on the gas card:**

Mercury's gas API returns empty `usage` arrays for `interval='daily'` and `'hourly'` requests on every account we've tested (documented in `mercury_api.py:980-984`). No reason to build UI for data Mercury doesn't expose.

**Color contrast accessibility:**

Yellow `rgb(255, 240, 0)` on the chart's dark background and gray `#727272` are visually distinguishable for the typical viewer. For colorblind users (deuteranopia, protanopia), brightness contrast (yellow is brighter than gray) supplements the hue distinction. Not a perfect accessibility solution; a future enhancement could add a hatch/pattern on estimated bars (Chart.js supports `pattern` plugin).

**v2.0.0 multi-ICP roadmap:**

This plan ships on `main` as v1.6.0. When the v2.0.0 branch (`fix/multi-icp-v200-phases-2-5`) is ready to merge, the card needs to be made multi-ICP-aware: the per-ICP attribute keys (`icp_<token>_gas_monthly_usage_history`) map to per-ICP sensor entities, and the user adds one card per gas ICP pointing at the right entity. The card JS itself doesn't need to change — only the Python side gets the per-ICP entity multiplication that v2.0.0 already implements for electricity.
