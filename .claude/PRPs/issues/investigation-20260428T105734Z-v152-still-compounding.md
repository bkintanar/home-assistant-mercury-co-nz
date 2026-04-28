# Investigation: gas dashboard 166,980 kWh on v1.5.2 — still compounding?

**Issue**: free-form (no GitHub issue)
**Type**: BUG (likely deployment, not code)
**Investigated**: 2026-04-28T10:57:34Z

### Assessment

| Metric     | Value  | Reasoning |
| ---------- | ------ | --------- |
| Severity   | MEDIUM | Wrong number on a single dashboard row; user already has the v1.5.2 code on disk and one full HA restart is the recovery. No data loss; no widening of impact. |
| Complexity | LOW    | Almost certainly a HACS-update-without-restart issue — zero new code changes needed. If a real code regression is found, a single-test integration scenario reproduces it. |
| Confidence | HIGH (deployment hypothesis); MEDIUM (rules out everything else) | Two parallel codebase agents traced every gas-statistic write path on `main@57a6122`. The math `(166,980 − 164,220) / 460 = exactly 6 cycles` matches a 30-minute window of v1.5.1 bytecode running while v1.5.2 files were on disk. Hypothesis 6 alternatives (anchor mismatch, race, multi-writer, tz handling) were each ruled out with file:line evidence. |

---

## Problem Statement

User on v1.5.2 (deployed via HACS) reports the gas energy dashboard for 27 March 2026 is still rising — `164,220 kWh → 166,980 kWh`. The v1.5.2 fix changed `cutoff_ts = last_ts_energy` (was `last_ts − 3 days`) so the most-recent imported entry is excluded from re-emission and the `sum` stops compounding. The fact that the value is rising means *something* is still re-emitting March 27 with an ever-larger `sum`.

---

## Analysis

### The arithmetic identity is too clean to be accidental

```
166,980 − 164,220 = 2,760
2,760 / 460        = 6.000 (exactly)
460                = user's actual 27 March consumption (pymercury consumption_periods)
```

**Six** additional compounding cycles occurred between the v1.5.1 baseline and the user's v1.5.2 reading. At the integration's 5-min coordinator interval (`DEFAULT_SCAN_INTERVAL = 5`, `const.py:29`), six cycles is a 30-minute window.

### Why this is almost certainly HACS-update-without-restart

HACS downloads the new `custom_components/mercury_co_nz/*.py` files to disk but **does not** hot-swap the running Python modules. The HA process keeps executing the v1.5.1 bytecode it imported at startup until HA is fully restarted. During the gap between "HACS finished writing files" and "HA was restarted", the still-running v1.5.1 code continues with its broken cutoff:

```python
# v1.5.1 (still running in memory after HACS file write)
cutoff_ts: float = (last_ts_energy or 0.0) - STATISTICS_REIMPORT_DAYS * 86400  # last_ts - 3 days
```

Each 5-min tick:
1. Reads `last_ts_energy = T_march27`, `last_sum_energy = 164,220` (then `164,680`, `165,140`, …) from recorder.
2. Computes `cutoff_ts = T_march27 − 259200`.
3. March 27's anchor `> cutoff_ts` → IS included in re-emission.
4. `energy_running = last_sum + 460` written back to the same row → recorder upserts, sum grows by 460.

Six ticks × 460 kWh/tick = +2,760 kWh = the observed delta.

After the user restarts HA, v1.5.2 bytecode loads. `cutoff_ts = T_march27`. Filter `anchor > T_march27` excludes March 27. The `sum` of the March 27 row is **frozen at 166,980** until manually corrected via HA Developer Tools → Statistics.

### Hypotheses ruled out (with file:line evidence)

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| 1 | Anchor mismatch — `consumption_periods` produces a different `invoice_to` shape from `daily_usage` | RULED OUT | `pymercury/api/models/base.py:202-209` passes `invoiceTo` through verbatim from Mercury's API into both `daily_usage` and (via group-by) `consumption_periods`. `_parse_invoice_end_utc` (`statistics.py:206-232`) yields identical UTC anchor `1774522800.0` for `"2026-03-27"`, `"2026-03-27T00:00:00"`, and `"2026-03-27T00:00:00+13:00"`. |
| 2 | Cutoff reads from a different `statistic_id` than v1.5.1 wrote | RULED OUT | `_build_metadata` (`statistics.py:149-184`) formula is byte-identical to v1.5.1 for the gas/primary case; `id_prefix` lock is persisted via Store. |
| 3 | `async_add_external_statistics` appends instead of upserting | RULED OUT | HA recorder `_import_statistics_with_session` (`venv/.../recorder/statistics.py:2734-2754`) calls `_statistics_exists(metadata_id, start_ts)` then `_update_statistics` on hit, `_insert_statistics` on miss. Genuine upsert keyed on `(metadata_id, start_ts)`. Same `start_ts` always overwrites. |
| 4 | Naive vs offset-aware tz handling silently shifts `start_ts` | RULED OUT | HA `_async_import_statistics` raises `HomeAssistantError` for naive datetimes; `_parse_invoice_end_utc` returns `tzinfo=timezone.utc`. Stored `start_ts = anchor.timestamp() = 1774522800.0`. |
| 5 | `_async_get_last_imported` returns `None` for `last_start` | RULED OUT | HA `_build_sum_stats` (`venv/.../recorder/statistics.py:_build_sum_stats`) populates `start` as the raw `start_ts` float. `get_last_statistics(n=1, ...)` orders `start_ts.desc()`. The most-recent row's `start` is always the float Unix timestamp. |
| 6 | Second writer (e.g., the v2.0.0 multi-ICP per-ICP importer) | RULED OUT | `coordinator.py:109-110` instantiates exactly one `MercuryStatisticsImporter(fuel_type="gas")` on `main@57a6122`. The v2.0.0 multi-importer commit lives only on `fix/multi-icp-v200-phases-2-5`. |
| 7 | Cost statistic compounding bleeds into the energy bar | RULED OUT | Cost is NZD-denominated, separate `statistic_id`; HA Energy Dashboard reads gas energy from the energy series only. |
| 8 | Recorder write/read race on the 5-min cadence | RULED OUT | `async_add_external_statistics` queues `ImportStatisticsTask` on the recorder's single-threaded executor; `get_last_statistics` runs on the same executor as a follow-up future. FIFO ordering guaranteed. |
| 9 | DST boundary | RULED OUT | NZ DST ends 2026-04-05; March 27 is firmly NZDT (+13). `ZoneInfo("Pacific/Auckland")` resolves correctly. |
| 10 | The fix didn't actually land at HEAD `57a6122` | RULED OUT | `git show 57a6122` confirms `cutoff_ts = last_ts_energy or 0.0` and `_build_hourly_entries` filter `<= cutoff_ts`. Both changes are present. 103 tests pass on main; 116 on the cherry-picked v2.0.0 branch. |

### Affected Files

No code changes required — the fix is correct. The remediation is operational:

| Action | Where | Description |
|---|---|---|
| Fully restart HA | Settings → System → Restart | Forces Python to re-import the v1.5.2 modules from disk |
| Clear inflated stat row | Developer Tools → Statistics → search `mercury_co_nz` gas → **Fix Issues** OR ⋯ menu → **Clear statistics** | The 166,980 frozen value lives in the recorder DB; v1.5.2 will not re-emit at that anchor |

### Integration Points

- `coordinator.py:243-251` — invokes `_gas_statistics.async_update(combined_data)` on every 5-min tick.
- `statistics.py:587-588` — sole `async_add_external_statistics` call site for gas.
- `statistics.py:561` (HEAD `57a6122`) — `cutoff_ts: float = last_ts_energy or 0.0`. Verify this line in the user's `/config/custom_components/mercury_co_nz/statistics.py` after restart.

### Git History

- `57a6122` (2026-04-28) — v1.5.2 fix landed, files written to GitHub release.
- `ddc4049` (2026-04-28) — v1.5.1 (pymercury 1.1.2 pin).
- The v1.5.1 → v1.5.2 window is small; the user almost certainly upgraded via HACS within hours of v1.5.2's GitHub release.

---

## Implementation Plan

### Step 1 — Verify v1.5.2 is actually loaded (not just on disk)

User runs in HA's Terminal & SSH add-on (or equivalent):

```bash
cat /config/custom_components/mercury_co_nz/manifest.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('version:', d['version']); print('requires:', d['requirements'])"
```

Expect: `version: 1.5.2`, `requires: ['aiohttp>=3.8.0', 'mercury-co-nz-api>=1.1.3']`.

If version reads `1.5.1`, the HACS update never landed — re-run the HACS update.

### Step 2 — Confirm v1.5.1 bytecode is no longer running

```bash
grep -r "STATISTICS_REIMPORT_DAYS" /config/custom_components/mercury_co_nz/
```

Expect: **no matches** (the constant was removed in v1.5.2). If it's still there, v1.5.1 files are on disk too — HACS may have left both in place, force-clean and re-install.

### Step 3 — Full HA restart

**Settings → System → Restart Home Assistant** (NOT a config-entry reload — that doesn't always re-import custom_components Python modules from disk; a full HA process restart does).

### Step 4 — Confirm v1.5.2 is now active

After restart, watch HA logs for:

```
Mercury statistics: nothing to import (cutoff_ts=1774522800.0, null_skipped=0)
```

(Expected at DEBUG level after the first post-restart coordinator tick. Enable debug logging via `Settings → System → Logs → Customize logging` for `custom_components.mercury_co_nz` if needed.)

If you see `Mercury statistics: imported 1 hourly entries (energy + cost), skipped 0 null records` for gas every 5 min, **the fix is not active** — go back to Step 1.

### Step 5 — Clear the inflated 166,980 row

**Developer Tools → Statistics**, search `mercury_co_nz`, find the gas energy statistic (id ends in `_gas_consumption`).

Two options:

**Option A (clean slate, safer)**: Click **⋯ → Clear statistics**, then wait one coordinator tick. The integration will see an empty recorder, set `last_ts_energy = None`, `last_sum_energy = 0.0`, and re-import the entire gas history from genesis with correct cumulative sums.

**Option B (surgical, faster)**: Use **Fix Issues** to spot-edit the bad row to a sensible value if HA exposes an editor. Less reliable; depends on HA version.

After Step 5, the dashboard should show `460 kWh` for 27 March (the actual consumption from pymercury `consumption_periods`).

---

## Patterns to Follow

This is operational guidance — no code patterns to mirror.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|---|---|
| User restarts but pymercury 1.1.3 didn't get installed (HA's pip cache has 1.1.2) | After restart, `pip show mercury-co-nz-api` in the HA container should report `1.1.3`. If `1.1.2`, force HA's pip to re-resolve via `pip install --upgrade mercury-co-nz-api`, then restart again. v1.5.2 is **defensive** against this case (`_collapse_gas_pairs` fallback in `mercury_api.py`), so the cutoff fix works regardless of pymercury version. |
| Clear-statistics removes ALL gas history, not just the bad row | Yes — Option A is intentionally a clean slate. The integration re-imports the whole 10-period series from pymercury on the next tick. Correct values land within ~5 min. |
| User had multiple inflated rows (not just March 27) from earlier v1.5.1 cycles | `_build_monthly_entries` only re-emits anchors `> cutoff_ts`. Once the most-recent anchor is March 27 (correctly stored), February and earlier are NEVER re-emitted, so any inflation from older v1.5.1 cycles is also frozen. Clearing the gas series via Step 5 wipes ALL of them and re-imports clean. |
| Future bug: the `_gas_statistics` importer instance is held in coordinator state across HA restart via Store | `Store` only persists `_id_prefix` (the email-hash lock); the running `MercuryStatisticsImporter` object is freshly instantiated each HA startup. No stale-state-across-restart risk. |

---

## Validation

### Automated Checks

```bash
cd /var/www/personal/home-assistant-mercury-co-nz
.venv/bin/python -m pytest custom_components/mercury_co_nz/tests/ --no-cov -q
```

Expect 103/103 passing on `main@57a6122`. Already verified.

### Manual Verification (the user's HA instance)

1. Step 1 confirms `1.5.2` on disk.
2. Step 2 confirms no v1.5.1 leftovers.
3. Step 3 fully restarts HA.
4. Step 4 confirms log says `nothing to import` for gas after one tick.
5. Step 5 clears the gas series.
6. After ~5 min: dashboard shows `460 kWh` for 27 March (and proper values for prior months — `397 kWh` for 26 February, etc.).

---

## Scope Boundaries

**IN SCOPE:**

- Operational remediation (restart + clear stale stats).
- Verifying the v1.5.2 fix is correctly deployed.

**OUT OF SCOPE:**

- New code changes — the fix is correct as shipped. The regression is a known-class HACS deployment issue, not a code bug.
- A test that simulates "HACS file swap mid-process" — Python doesn't support that; HA can't realistically defend against partial-deployment compounding without checksumming its own bytecode against disk on every tick.
- Adding HACS auto-restart — that's a HACS-level setting on the user's side, not something this integration controls.
- Documenting the post-update restart in the README — likely worth doing as a follow-up but not a blocker for this artifact.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-28T10:57:34Z
- **Artifact**: `.claude/PRPs/issues/investigation-20260428T105734Z-v152-still-compounding.md`
- **Branch at investigation**: `main` (HEAD `57a6122`, v1.5.2)
- **Related**:
  - Prior investigation: `/var/www/personal/pymercury/.claude/PRPs/issues/investigation-gas-164220-ha-recurrence.md` (the 164,220 root cause).
  - Shipped fix: PR #20 (squash-merged as `57a6122`), released as v1.5.2.
- **Confidence**: HIGH for the HACS-update-no-restart hypothesis (math + ruled-out alternatives). MEDIUM that this fully explains the user's observation — small residual chance that `pip` didn't install pymercury 1.1.3 and the user is on an unexpected version. Step 1 + Step 4 verify both at once.
