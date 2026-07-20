# Investigation: Issue #27 follow-up — Current Rate "Unknown", weekly summary empty, disabling gas

**Issue**: [#27](https://github.com/bkintanar/home-assistant-mercury-co-nz/issues/27) (follow-up after v1.6.6 fix)
**Type**: Mixed — one BUG (concern 1), one WORKING-AS-INTENDED / DOC (concern 2), one ENHANCEMENT (concern 3)
**Investigated**: 2026-07-21

> Context: #27's original "not polling / missing information" crash was fixed in **v1.6.6** (`pymercury` null-summary guard). After updating, reporter **@Mr-Cake** replied 2026-07-20 with a sensor screenshot and three *new* questions. This investigation addresses those three. The original crash is resolved and confirmed — the follow-up items are separate.

Screenshot state (all electricity, no gas customer): **Current Plan = "Current Rates"** ✅, **Daily Fixed Charge = 1.725 NZD/day** ✅, **Current Rate = Unknown** ❌, all `weekly_*`/usage/bill sensors = `0`.

---

## Assessment (per concern)

| Concern | Metric | Value | Reasoning |
|---------|--------|-------|-----------|
| **1. Current Rate = Unknown** | Severity | **MEDIUM** | The rate is the feature the user most wants, but no crash and every other sensor works; it is plan-shape–specific, not a universal outage. |
| | Complexity | **MEDIUM** | Fix most likely lives in `pymercury` (widen unit-rate extraction) ± new per-rate sensors here; needs the user's raw plans JSON to target. |
| | Confidence | **MEDIUM-HIGH** | *Mechanism* is HIGH-confidence and fully traced (`anytime_rate` → `None` → unit not in zero-fallback list → "Unknown"); the *exact upstream trigger* (empty vs multi-rate `unitRates`) needs one data capture. |
| **2. Weekly summary = 0** | Priority | **LOW** | Working as intended — data-availability, not account-type; recently-joined accounts have no full week yet. Only real gap is missing test coverage. |
| | Confidence | **HIGH** | Fully traced; matches the same null-`weeklySummary` behaviour behind the v1.6.6 fix. |
| **3. Disable gas for non-gas accounts** | Priority | **MEDIUM** | Real UX papercut for electricity-only customers (two permanent `0` gas sensors); requested directly. |
| | Complexity | **LOW** | ~1 guarded loop in `sensor.py` + a test; gas data/statistics are *already* gated on `is_gas`. |
| | Confidence | **HIGH** | Root cause is a single unconditional loop; the gating pattern to mirror already exists elsewhere in the coordinator. |

---

## Concern 1 — "Current Rate" shows Unknown

### Problem Statement
The **Current Rate** sensor (`sensor.*_current_rate`, key `plan_anytime_rate`) reads **Unknown** while **Current Plan** and **Daily Fixed Charge** — parsed from the *same* Mercury `/electricity/plans` response — populate correctly. So the plans call is succeeding; only the per-kWh unit rate is missing.

### Why this is NOT the old issue #6
Prior investigation `completed/issue-6-current-rate-not-working.md` covered **all 5** `plan_*` sensors going blank because `get_electricity_plans()` returned `{}` (auth/ICP/HTTP failure upstream). Here, Current Plan + Daily Fixed Charge **do** populate, so `get_electricity_plans()` returned real data. This is a **narrower, distinct** cause: the plan parsed, but no single "anytime" unit rate could be extracted.

### Evidence chain
WHY: `Current Rate` renders "Unknown".
↓ BECAUSE: `native_value` returned `None`.
Evidence: `sensor.py:259-292` — `raw_value is None` and unit `"NZD/kWh"` is **not** in the zero-fallback list `["kWh", "$", "°C", "days", "%"]`, so it returns `None` (→ "Unknown"), unlike `"$"`/`"kWh"` sensors which fall back to `0`.

↓ BECAUSE: `coordinator.data["plan_anytime_rate"]` is `None`.
Evidence: `mercury_api.py:632` — `"anytime_rate": self._parse_rate_amount(anytime_raw, anytime_measure)`; `_parse_rate_amount(None, …)` returns `None` immediately (`mercury_api.py:560-561`). `daily_fixed_charge` (`:633`) parsed fine → the plan object itself is populated.

↓ ROOT CAUSE: `pymercury`'s `ElectricityPlans.anytime_rate` resolved to `None`.
Evidence: `.venv/.../pymercury/api/models/electricity.py:151-160` — `anytime_rate` is set only if a `unitRates` entry is named `anytime`/`inclusive`, **or** there is exactly one unit rate. It stays `None` when the plan has **multiple** unit rates (TOU: day/night, peak/off-peak, controlled/uncontrolled) none named anytime/inclusive, **or** `unitRates` is empty. `daily_fixed_charge` comes from `otherCharges` (`:134-144`), a different array — which is why it populated (1.725) while `anytime_rate` did not.

### Affected files
| File | Lines | Notes |
|------|-------|-------|
| `pymercury/api/models/electricity.py` | 146-160 | Where `anytime_rate` fails to resolve (likely fix site) |
| `custom_components/.../mercury_api.py` | 603-652, 541-601 | Normalization; correct — faithfully passes through `None` |
| `custom_components/.../sensor.py` | 259-292 | `None` → "Unknown" for `NZD/kWh` (by design; see const.py:292-296) |
| `custom_components/.../const.py` | 297-303 | `plan_anytime_rate` sensor def |

### Required next step (data capture — one round-trip with the user)
The exact trigger (empty `unitRates` vs multi-rate plan) is only distinguishable from the user's actual response. Ask @Mr-Cake to enable debug logging and share the raw plans payload:
```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.mercury_co_nz: debug
    pymercury: debug
```
Then look in the log for the `Normalized plans data: …` line (`mercury_api.py:647`) and pymercury's plans debug — specifically the `unitRates` array (count + `name`/`rate`/`measure` of each entry).

### Likely fixes (choose after seeing the data)
- **A (most likely, in `pymercury`)**: widen `anytime_rate` extraction so a single-rate plan whose lone unit rate is named something new (Mercury has renamed before — v1.6.7/issue #6 = "Inclusive") still resolves; and/or expose all `unitRates` so multi-rate plans aren't reduced to one number.
- **B (in this repo)**: if the plan is genuinely TOU/multi-rate, add per-rate sensors (e.g. `plan_day_rate`/`plan_night_rate`) instead of the single `plan_anytime_rate`, so multi-rate customers get their prices.
- Either way, `plan_anytime_rate` staying `None` for true multi-rate plans is defensible; the user experience gap is that there's then *no* rate sensor at all.

---

## Concern 2 — Weekly summary sensors show 0

### Answer (working as intended)
Weekly summary is **not account-type dependent**. The `weekly_*` sensors are built Monday→Sunday from Mercury's `weeklySummary.usage[]` array (`pymercury .../electricity.py:39-52`; normalized at `mercury_api.py:213-230`). Mercury returns **`weeklySummary: null`** until the account has a *full* week of interval/daily meter data — which is exactly the recently-joined-account situation behind the original #27 crash (now safely coerced to empty in v1.6.6). With no weekly data, no `weekly_*` keys land in `coordinator.data` (`coordinator.py:165-172`), so `weekly_usage_cost` (unit `$`) falls back to `0` and `weekly_usage_history`/`weekly_notes` return `0` (`sensor.py:295-306`).

So: the user's monthly-only *billing breakdown* is unrelated — weekly usage will populate once Mercury has accumulated ~a full week of the account's daily reads. If it never populates after several weeks, that's a separate data-availability question for Mercury (e.g. non-interval meter).

### Coverage gap (worth a small follow-up)
There is a unit test for the `plan_*` None path (`tests/test_plans.py:58-63`) but **no** equivalent for `_normalize_weekly_summary_data` returning `{}` on absent/`null` `weeklySummary`. Recommend adding `tests/test_weekly.py` to lock in the v1.6.6 behaviour.

---

## Concern 3 — Allow disabling gas for non-gas customers

### Root cause
Gas **data fetch** and **long-term statistics** are already correctly gated on `is_gas`:
- discovery `coordinator.py:313-315` (`_discovered_gas_services`)
- fetch gate `coordinator.py:126-132`
- statistics gate `coordinator.py:345-353`
- API gate `mercury_api.py:925-928`

But the two gas **sensor entities** are created **unconditionally**. `sensor.py:57-66` iterates *every* `SENSOR_TYPES` key not in `ICP_SCOPED_SENSOR_TYPES`, which includes `gas_monthly_usage` (`const.py:175-184`) and `bill_gas_amount` (`const.py:168-174`) — with no reference to `_discovered_gas_services`. Result: electricity-only customers get two permanent `0` gas sensors.

### Implementation plan
| Step | File | Change |
|------|------|--------|
| 1 | `sensor.py:57-66` | Skip gas sensor types when `not coordinator._discovered_gas_services`. Mirror the existing `is_gas` gating pattern. |
| 2 | `const.py` | Add a `GAS_SENSOR_TYPES` frozenset (`{"gas_monthly_usage", "bill_gas_amount"}`) so the skip is declarative, not string-matched. |
| 3 | `tests/` | Add a test asserting gas sensors are absent when the account has no gas service (none exists today — confirmed across `test_gas_pipeline.py`, `test_multi_icp.py`). |

**Current code (`sensor.py:57-66`):**
```python
for sensor_type in SENSOR_TYPES:
    if sensor_type in ICP_SCOPED_SENSOR_TYPES:
        continue
    entities.append(MercurySensor(coordinator, sensor_type, name, email,
                                   service_id=None, is_primary=True, fuel_type=None))
```
**Change:**
```python
has_gas = bool(coordinator._discovered_gas_services)
for sensor_type in SENSOR_TYPES:
    if sensor_type in ICP_SCOPED_SENSOR_TYPES:
        continue
    if sensor_type in GAS_SENSOR_TYPES and not has_gas:
        continue
    entities.append(MercurySensor(coordinator, sensor_type, name, email,
                                   service_id=None, is_primary=True, fuel_type=None))
```
**Note**: this affects new setups on reload/restart. Users who already have the `0` gas sensors will have them removed on the next restart after upgrade (HA marks them as orphaned entities they can delete).

---

## Scope Boundaries
**IN SCOPE:** diagnosing the three follow-up concerns; a contained gas-gating enhancement; a documented answer + data-capture ask for the rate issue.

**OUT OF SCOPE (defer / separate issue):**
- Actually shipping the Current Rate fix — blocked on the user's raw plans JSON; likely a `pymercury` release. Recommend splitting into its own **bug** issue once the data confirms the trigger.
- Multi-rate/TOU per-rate sensor design — its own enhancement.
- Reworking the `weekly_*` behaviour — it's correct; only a test is missing.

---

## Recommended issue hygiene
#27 is a **fixed bug** held open only for @Mr-Cake's confirmation of the v1.6.6 crash fix. The three follow-ups are separate concerns. Recommend: post this consolidated answer on #27, confirm the crash fix, then split **concern 1 (bug)** and **concern 3 (enhancement)** into dedicated issues so #27 can close cleanly.

---

## Validation (for the gas enhancement, when implemented)
```bash
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/ -q
```
Manual: on an electricity-only account, confirm `sensor.*_gas_monthly_usage` and `sensor.*_gas_amount` are not created; on a gas account, confirm they still are.

---

## Metadata
- **Investigated by**: Claude
- **Timestamp**: 2026-07-21
- **Artifact**: `.claude/PRPs/issues/issue-27-followup.md`
