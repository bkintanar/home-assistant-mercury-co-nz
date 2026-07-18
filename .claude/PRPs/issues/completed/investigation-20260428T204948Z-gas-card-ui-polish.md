# Investigation: Gas card UI polish — legend, info-panel coloring, layout

**Issue**: free-form (no GitHub issue)
**Type**: ENHANCEMENT
**Investigated**: 2026-04-28T20:49:48Z

### Assessment

| Metric     | Value  | Reasoning |
| ---------- | ------ | --------- |
| Priority   | MEDIUM | All five changes are visual polish on the v1.6.0 gas card — non-blocking, no data correctness impact. The user is actively using the card and the friction (yellow legend swatch that should be gray, redundant `(estimated)` text, info panel doesn't reflect estimate state) is real but cosmetic. |
| Complexity | LOW    | All changes scoped to one file (`gas-monthly-summary-card.js`) plus the local `static styles` CSS block. Zero changes to shared `styles.js` (which would risk breaking other cards). No Python, no tests, no JS data-flow changes. |
| Confidence | HIGH   | Each change is a small targeted edit with a clear, demonstrable visual outcome. Read the rendered card, applied each change, can trace exactly which DOM/style line each change affects. |

---

## Problem Statement

Five focused visual improvements to the v1.6.0 gas-monthly-summary-card:

1. The "Estimated" **legend** swatch renders yellow despite the underlying CSS rule `.legend-circle.estimated { background-color: #727272 }` — likely a CSS specificity / cascade order issue inside the shadow DOM. Inline-style the gray to be unambiguous.
2. The **info panel below the chart** says `Your gas usage for this billing period (estimated)` when an estimate bar is selected. The `(estimated)` text is redundant given the bars themselves are color-coded; remove it.
3. When an estimate bar is selected (or is the auto-selected current bar), the **info-panel background should turn gray** (matching the gray bar) instead of staying yellow. Yellow is reserved for actuals.
4. **Add a 🔥 fire emoji** to the left of `Your gas usage for this billing period` (matches the gas/fire mental model and provides visual anchor at the start of the line).
5. **Align** `$X.XX | XXX kWh` on the same row as `Your gas usage for this billing period` (currently they're stacked vertically; the user wants them inline so the panel reads as a single horizontal status line).

---

## Analysis

### Change Rationale

The gas card visually communicates two states (actual / estimated) through bar color (yellow / gray). The legend swatch and info-panel background both need to reflect the same coloring vocabulary so the user gets reinforced signal:

- **Bar yellow → actual**, **bar gray → estimated** ✅ (already working)
- **Legend yellow circle "Actual"**, **legend gray circle "Estimated"** ⚠️ (gray rule exists but not rendering — needs inline-style to override)
- **Info panel yellow when actual selected**, **info panel gray when estimated selected** ❌ (currently always yellow)

The redundant `(estimated)` text becomes unnecessary once the panel's own color reflects the state.

The fire emoji + horizontal layout convert the panel from a stacked two-line widget into a single status line, which reads more naturally in dashboards alongside the chart.

### Where the current code is

- **`custom_components/mercury_co_nz/gas-monthly-summary-card.js`** (HEAD `118cf59`, v1.6.1):
  - `static styles` block (lines 12-23) — local card-specific CSS overrides. Currently defines `.estimate-tag`. This is where ALL new gas-card-specific CSS should go.
  - `_renderGasCard()` (lines 437-466) — renders `.chart-info` with the inner usage details.
  - `_renderCustomLegend()` (lines 497-510) — renders the two legend items.
- **`custom_components/mercury_co_nz/styles.js`** (HEAD `118cf59`):
  - `.chart-info` rule at lines 226-237 — yellow background, flex with `flex-start`, used by all chart cards. **DO NOT MODIFY** (would affect other cards).
  - `.legend-circle` rule at lines 511-517 — yellow circle. Used by all cards.
  - `.legend-circle.estimated` rule at lines 519-521 — gray circle. **Exists but apparently not winning specificity** in user's render. The fix is to inline-style the legend element directly so cascade can't lose.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `custom_components/mercury_co_nz/gas-monthly-summary-card.js` | 12-23 | UPDATE | Add card-scoped CSS overrides for the new conditional `chart-info.estimated` background, the horizontal `usage-details` flex layout, the fire-emoji span, and a defensive inline gray for the legend circle. Drop `.estimate-tag` (no longer used). |
| `custom_components/mercury_co_nz/gas-monthly-summary-card.js` | 450-462 | UPDATE | Conditionally apply `estimated` class to `.chart-info`. Reorganize inner markup so date + stats are siblings. Add fire-emoji span. Drop the `(estimated)` text span. |
| `custom_components/mercury_co_nz/gas-monthly-summary-card.js` | 497-510 | UPDATE | Inline-style the gray on the second `.legend-circle` for cascade-immunity. |
| `custom_components/mercury_co_nz/manifest.json` | 13 | UPDATE | Bump `1.6.1` → `1.6.2` (patch — UI polish only). |

### Integration Points

- The card renders inside HA's Lovelace dashboard via shadow DOM. CSS scoping means the card's `static styles` block applies only to this card's tree — no leakage to other cards.
- `_selectedDate.is_estimated` (already populated by `_updateSelectedInfo()` at line 322) provides the boolean used to gate the `estimated` class on `.chart-info`. No new state plumbing needed.

### Git History

- `118cf59` (2026-04-29) — v1.6.1 introduced `_attr_has_entity_name=True` (entity_id cleanup) but left the card's UI unchanged from v1.6.0.
- `18ade46` (2026-04-29) — v1.6.0 created the gas card. Original `(estimated)` tag and layout from this commit.
- This is the first round of UI feedback on the new card. Polish iteration is expected and welcome.

---

## Implementation Plan

### Step 1 — Update card-scoped CSS in `static styles`

**File**: `custom_components/mercury_co_nz/gas-monthly-summary-card.js`
**Lines**: 12-23
**Action**: REPLACE the existing static styles block

**Current code:**

```javascript
static styles = [
  mercuryChartStyles,
  css`
    /* Gas card-specific overrides — .legend-circle.estimated lives
       in chartLegendStyles for cross-card reuse. */
    .estimate-tag {
      margin-left: 6px;
      opacity: 0.75;
      font-style: italic;
    }
  `
];
```

**Required change:**

```javascript
static styles = [
  mercuryChartStyles,
  css`
    /* Gas card-specific overrides. The chart-info background reflects the
       selected period's read type — yellow for actual reads, gray for
       Mercury estimates — matching the bar color. */
    .chart-info.estimated {
      background: #727272;
    }
    .chart-info.estimated .usage-date,
    .chart-info.estimated .usage-stats {
      color: white;
    }

    /* Single-row layout: "🔥 Your gas usage for this billing period   $X.XX | XXX kWh"
       falls back to wrapped on narrow screens. */
    .usage-details {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 16px;
    }
    .usage-date {
      margin-bottom: 0; /* override stacked-layout default */
    }
    .usage-stats {
      font-weight: 600;
    }

    .fire-emoji {
      margin-right: 6px;
      font-size: 16px;
      line-height: 1;
    }
  `
];
```

**Why**: Card-scoped overrides only — no shared-stylesheet edits. The `.chart-info.estimated` cascade wins over the base `.chart-info` rule because it's both more specific (compound selector) AND defined later in the rendered stylesheet (lit concatenates `mercuryChartStyles` first, then this block). The base layout flex (`flex-direction: row`, `justify-content: flex-start`) inherited from `.chart-info` is preserved; we only flip the inner `.usage-details` to flex so date + stats become siblings on one row.

---

### Step 2 — Update `_renderGasCard()` info panel markup

**File**: `custom_components/mercury_co_nz/gas-monthly-summary-card.js`
**Lines**: 450-462
**Action**: UPDATE the `<div class="chart-info">` block

**Current code:**

```javascript
<div class="chart-info">
  <div class="data-info">
    ${this._selectedDate ? html`
      <div class="usage-details">
        <div class="usage-date">
          Your gas usage for this billing period
          ${this._selectedDate.is_estimated ? html`<span class="estimate-tag">(estimated)</span>` : ''}
        </div>
        <div class="usage-stats">$${this._selectedDate.cost.toFixed(2)} | ${this._selectedDate.consumption.toFixed(2)} kWh</div>
      </div>
    ` : html`Loading...`}
  </div>
</div>
```

**Required change:**

```javascript
<div class="chart-info ${this._selectedDate?.is_estimated ? 'estimated' : ''}">
  <div class="data-info">
    ${this._selectedDate ? html`
      <div class="usage-details">
        <div class="usage-date">
          <span class="fire-emoji">🔥</span>Your gas usage for this billing period
        </div>
        <div class="usage-stats">$${this._selectedDate.cost.toFixed(2)} | ${this._selectedDate.consumption.toFixed(2)} kWh</div>
      </div>
    ` : html`Loading...`}
  </div>
</div>
```

**Why**:

- The conditional `${this._selectedDate?.is_estimated ? 'estimated' : ''}` adds the `estimated` class only when the active bar is an estimate — gating the gray background.
- The `(estimated)` text-span is dropped (the panel color now communicates that state).
- `<span class="fire-emoji">🔥</span>` prefix on the description line. Inline `<span>` instead of plain emoji char so the CSS rule can target it for spacing/sizing.
- The inner `.usage-details` is now a flex container (per Step 1's CSS), so the two child divs render on the same row instead of stacking.
- Optional-chaining (`?.`) on `_selectedDate` keeps the loading state safe — `undefined.is_estimated` would throw without it.

---

### Step 3 — Update `_renderCustomLegend()` to force gray on the estimated swatch

**File**: `custom_components/mercury_co_nz/gas-monthly-summary-card.js`
**Lines**: 497-510
**Action**: UPDATE the legend renderer

**Current code:**

```javascript
_renderCustomLegend() {
  return html`
    <div class="custom-legend">
      <div class="legend-item">
        <div class="legend-circle"></div>
        <span class="legend-label">Actual</span>
      </div>
      <div class="legend-item">
        <div class="legend-circle estimated"></div>
        <span class="legend-label">Estimated</span>
      </div>
    </div>
  `;
}
```

**Required change:**

```javascript
_renderCustomLegend() {
  // Inline style on the estimated swatch so cascade order can't lose to
  // the base `.legend-circle` rule (the styles.js rule `.legend-circle.estimated`
  // exists but doesn't always win in the rendered shadow DOM — use inline to
  // guarantee gray).
  return html`
    <div class="custom-legend">
      <div class="legend-item">
        <div class="legend-circle"></div>
        <span class="legend-label">Actual</span>
      </div>
      <div class="legend-item">
        <div class="legend-circle" style="background-color: #727272;"></div>
        <span class="legend-label">Estimated</span>
      </div>
    </div>
  `;
}
```

**Why**: Inline `style="..."` has the highest CSS specificity (1,0,0,0) of any non-`!important` rule and beats anything declared in either the shared `mercuryChartStyles` or the card's `static styles`. The `.estimated` modifier class is dropped from this element; we don't need it once the inline style is on. The shared `.legend-circle.estimated` rule in `styles.js` stays in place for any future card that wants to use it.

---

### Step 4 — Bump manifest version

**File**: `custom_components/mercury_co_nz/manifest.json`
**Lines**: 13
**Action**: UPDATE

**Current code:**

```json
"version": "1.6.1"
```

**Required change:**

```json
"version": "1.6.2"
```

**Why**: Patch bump — UI polish only, no behavior changes for data flow, no breaking changes for users. HACS picks up the bump and the integration's frontend resource URLs gain `?v=1.6.2`, busting browser cache for `gas-monthly-summary-card.js` so the new render lands without hard-refresh.

---

### Step 5 — No new tests

UI changes have no test coverage in this repo (zero JS test infrastructure, verified earlier in the v1.6.0 implementation). Visual verification is via browser/HA only. No Python tests are affected.

---

## Patterns to Follow

**Conditional class binding (lit-html idiom):**

```javascript
// SOURCE: gas-monthly-summary-card.js:478 (existing nav-arrow disabled pattern)
<span class="nav-arrow ${this._isNavDisabled('prev') ? 'nav-arrow-hidden' : ''}">
```

The same pattern applied to `chart-info`:

```javascript
<div class="chart-info ${this._selectedDate?.is_estimated ? 'estimated' : ''}">
```

**Card-scoped style overrides via lit `static styles`:**

```javascript
// SOURCE: gas-monthly-summary-card.js:12-23 (current pattern)
static styles = [
  mercuryChartStyles,           // shared base
  css`
    .gas-card-specific-rule {   // override
      ...
    }
  `
];
```

Lit applies the array of stylesheets in order; later sheets override earlier ones at equal specificity. Card-specific tweaks belong in the second slot.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|---|---|
| `_selectedDate` is null on initial render (loading state) | `_selectedDate?.is_estimated` short-circuits to `undefined`, the conditional renders empty class string. No crash, no spurious gray. |
| User has dark theme — gray (#727272) on dark background may have poor contrast | The `.chart-info.estimated .usage-date / .usage-stats` rule sets text color to `white` regardless of theme. Gray-on-dark-card contrast remains adequate (text is white). |
| Narrow viewport (<480px) — single-row layout could overflow | `flex-wrap: wrap` on `.usage-details` falls back to stacked layout on narrow screens. Both children retain their respective styles. |
| Cherry-pick onto v2.0.0 branch conflicts | Card file is identical between branches (v2.0.0 only differs in Python multi-ICP code). Cherry-pick should apply cleanly. |
| Existing users hitting the cached old `gas-monthly-summary-card.js` | Manifest version bump (1.6.1 → 1.6.2) busts the `?v=` query string on the Lovelace resource URL. Browser fetches the new JS on next dashboard load. |
| The `.legend-circle.estimated` shared rule is technically dead code after Step 3 | Leave it in `styles.js` as documentation / future-card scaffolding. Removing it would risk other cards that might use the same pattern. |

---

## Validation

### Automated Checks

```bash
cd /var/www/personal/home-assistant-mercury-co-nz
node --check custom_components/mercury_co_nz/gas-monthly-summary-card.js && echo "JS OK"
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/ --no-cov -q
```

**EXPECT**: JS syntax OK; 110/110 tests pass (no Python test changes; existing Python tests do not exercise card render).

### Manual Verification (the user's HA instance, after deploy + restart)

1. **Legend swatch**: open dashboard with the gas card → confirm "Estimated" legend item shows a **gray** circle (not yellow).
2. **No `(estimated)` text**: click any estimated bar (gray) → info panel reads exactly `🔥 Your gas usage for this billing period   $X.XX | XXX kWh`. No parenthetical "(estimated)".
3. **Gray panel on estimate**: click any gray bar → info panel background turns **gray with white text**. Click any yellow bar → panel returns to **yellow with black text**.
4. **Fire emoji**: panel description starts with 🔥 followed by space then "Your gas usage…".
5. **Same row**: description and `$cost | kWh` are visually inline on a desktop dashboard (>= 480px viewport). On mobile they may wrap to two lines but both remain left-aligned.
6. **Initial state** (page just loaded): card auto-selects the latest bar; if that bar is an estimate, the panel renders gray immediately. No flash of yellow.

---

## Scope Boundaries

**IN SCOPE:**

- All five UI changes listed in the problem statement, scoped to `gas-monthly-summary-card.js` and a manifest version bump.
- Card-local CSS overrides (no edits to shared `styles.js`).

**OUT OF SCOPE:**

- Removing the `.legend-circle.estimated` rule from `styles.js`. Leave it in place for any future card that wants it.
- Animating the panel color transition. CSS `transition: background 0.2s ease` could be added but is unnecessary polish for now; the user did not request it.
- Adding the `(estimated)` text back as an aria-label or hover tooltip for accessibility. Could be a v1.7.0 enhancement; not requested here.
- Recolouring or restyling the existing electricity cards. They keep their current yellow-only legend.
- Cherry-picking this onto the v2.0.0 branch as part of THIS work. Defer to the v2.0.0 release flow.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-28T20:49:48Z
- **Artifact**: `.claude/PRPs/issues/investigation-20260428T204948Z-gas-card-ui-polish.md`
- **Branch at investigation**: `main` (HEAD `118cf59`, v1.6.1)
- **Related**:
  - v1.6.0 plan: `.claude/PRPs/plans/gas-monthly-summary-card.plan.md` (introduced the card).
  - v1.6.1 fix: PR #22 (entity_id naming).
- **Confidence**: HIGH. All five changes are visually verifiable without code introspection; their implementation is constrained to one card file plus a one-character manifest bump.
