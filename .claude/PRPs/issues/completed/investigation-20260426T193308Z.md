# Investigation: Use real per-hour Mercury usage in HA Energy Dashboard (instead of synthetic 24-hour daily split)

**Issue**: free-form (no GitHub issue)
**Type**: ENHANCEMENT
**Investigated**: 2026-04-26T19:33:08Z

### Assessment

| Metric     | Value  | Reasoning                                                                                                                                                                                                         |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Priority   | HIGH   | The Energy Dashboard is the integration's headline feature (README §"🔋 Energy Dashboard Integration") and currently shows misleading flat hourly profiles (kWh ÷ 24) instead of the real hourly data the API returns. |
| Complexity | MEDIUM | Three files (`statistics.py`, `coordinator.py`, `tests/test_statistics.py`); one new helper, one merge-of-two-sources change, one retention-window bump. No architectural changes — both data sources already flow into `combined_data`.       |
| Confidence | HIGH   | Both data sources (daily + hourly) already arrive at `statistics.py:async_update` in `combined_data`. The single decision point is `statistics.py:283-286`. Frontend cards read sensor attributes, not statistics, so no card regression risk. |

---

## Problem Statement

User reports that under HA's official **Settings → Dashboards → Energy** dashboard, the `Mercury <id> consumption` series shows only a daily total (effectively a flat hourly profile) even though the integration fetches genuine per-hour usage from Mercury's API. The user wants the dashboard's hourly bins to reflect the real per-hour consumption Mercury delivers, not a daily total spread evenly across 23/24/25 hours.

## What's actually happening

`mercury_api.py:880` calls `get_electricity_usage_hourly`, returning per-hour `consumption` and `cost`. `coordinator.py:138` persists those rows into `www/mercury_hourly.json` (7-day cache). `coordinator.py:157` reloads them into `combined_data["extended_hourly_usage_history"]`. They sit there unused: `statistics.py:283-286` reads only `extended_daily_usage_history` (or `daily_usage_history` as fallback) and `_build_hourly_entries` (`statistics.py:151`) divides each daily kWh/cost by `hours_in_day` (23/24/25) to fabricate hourly bins. The README's claim that "Mercury provides daily-resolution data only" is incorrect — it's a stale design note from before the hourly API was wired in (hourly storage commit `a791f7b`, 2025-08-15; statistics importer commit `ed94909`, 2026-04-27 — eight months later).

---

## Analysis

### Change Rationale

The integration already pays for hourly data (it fetches, parses, persists, and exposes it via sensor attributes for the custom Lovelace card). Only the statistics importer ignores it. Switching the importer to consume real hourly bins gives the official HA Energy Dashboard a genuine hourly profile (e.g., morning/evening peaks visible) instead of 24 identical bars per day.

### Evidence Chain

WHY: The HA Energy Dashboard hourly view shows a flat consumption profile / "only the total" for Mercury.

↓ BECAUSE: Every hour of a given day gets the same `state` value.
Evidence: `custom_components/mercury_co_nz/statistics.py:206-207` — `hourly_kwh = float(consumption) / hours_in_day; hourly_cost = float(cost) / hours_in_day`, then emitted unchanged for each of the 23/24/25 hours of that NZ-local day at `statistics.py:216-229`.

↓ BECAUSE: `_build_hourly_entries` is fed daily totals, not hourly buckets.
Evidence: `statistics.py:283-286` — the only data-source selector in the importer:
```python
records = coordinator_data.get(
    "extended_daily_usage_history"
) or coordinator_data.get("daily_usage_history")
```

↓ BECAUSE: The hourly data is never read by the importer, even though the coordinator puts it on the same dict.
Evidence: `coordinator.py:157-163` populates `combined_data["extended_hourly_usage_history"]`, then `coordinator.py:181` calls `self._statistics.async_update(combined_data)`, but the `extended_hourly_usage_history` key (and the freshly-fetched `hourly_usage_history` key) are never accessed inside `statistics.py`.

↓ ROOT CAUSE: The importer was written eight months after the hourly cache was added and adopted the pre-existing `daily → split` shape. There's no comment/TODO acknowledging the hourly cache; the importer's docstring at `statistics.py:48-53` still asserts "Mercury's API delivers daily totals" — outdated.
Evidence: `git log custom_components/mercury_co_nz/statistics.py` → only commit is `ed94909` (2026-04-27). `git log custom_components/mercury_co_nz/coordinator.py | grep hour` → `a791f7b` (2025-08-15) "stores 7 days worth of hourly energy usage". README §"🔋 Energy Dashboard Integration" still echoes the stale assumption.

### Affected Files

| File                                                            | Lines       | Action | Description                                                                                                                                                                                                    |
| --------------------------------------------------------------- | ----------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `custom_components/mercury_co_nz/statistics.py`                 | 150-232     | UPDATE | Add a hourly-records branch in `_build_hourly_entries` (or extract a new helper) so each hourly record produces ONE entry instead of 23/24/25. Keep the daily-split path for older records not yet covered by the hourly cache. |
| `custom_components/mercury_co_nz/statistics.py`                 | 234-356     | UPDATE | In `async_update`, build the hourly-covered NZ-day set, partition records, and merge results from both sources sorted by `start` so cumulative `sum` is monotonic.                                              |
| `custom_components/mercury_co_nz/statistics.py`                 | 46-53       | UPDATE | Refresh class docstring — Mercury delivers BOTH daily and hourly; the importer prefers real hourly for recent days, falls back to spread daily for older days outside the hourly cache window.                  |
| `custom_components/mercury_co_nz/coordinator.py`                | 195, 242-267, 437-438 | UPDATE | Bump hourly JSON cache retention from 7 to 180 days so the hourly-statistics window matches the daily-statistics window over time. Update log strings ("7 days" → "180 days") and method docstrings.            |
| `custom_components/mercury_co_nz/const.py`                      | 329-336     | UPDATE | Add `STATISTICS_HOURLY_RETENTION_DAYS: Final[int] = 180`. Wire it into `coordinator.py` instead of the magic `timedelta(days=7)`.                                                                              |
| `custom_components/mercury_co_nz/tests/test_statistics.py`      | NEW tests   | UPDATE | Add: hourly records → 1 entry each; mixed daily+hourly merge keeps cumulative `sum` monotonic and chronologically sorted; daily fallback still works when `extended_hourly_usage_history` is empty.            |
| `README.md`                                                     | line ~93    | UPDATE | Replace "Mercury provides daily-resolution data only; the integration spreads each daily total across 23/24/25 hourly bins (DST-aware)" with text reflecting the new behaviour: hourly when available, daily-spread for older days outside the hourly window. |
| `custom_components/mercury_co_nz/manifest.json`                 | line 13     | UPDATE | Bump version `1.2.4` → `1.3.0` (minor — Energy Dashboard fidelity improvement).                                                                                                                                |

### Integration Points

- `coordinator.py:181` calls `self._statistics.async_update(combined_data)` — only entry into `statistics.py`. No other module imports the statistics importer.
- `__init__.py:80` (`async_setup_entry`) constructs the coordinator with a 5-minute interval; statistics import runs once per cycle.
- `coordinator.py:38` instantiates `MercuryStatisticsImporter`; it owns the recorder-failure backoff state, so async_update must remain the single call site.
- Custom Lovelace cards (`energy-usage-card.js`, `energy-monthly-summary-card.js`, `energy-weekly-summary-card.js`) consume sensor entity attributes only (`entity.attributes.hourly_usage_history`, etc.) — they do NOT read HA long-term statistics. **Out of scope; unaffected by this change.**
- `sensor.py:264-309` truncates daily/hourly history attributes (45-day daily, 48-hour hourly) — out of scope; unaffected.

### Git History

- **Hourly cache introduced**: `a791f7b` (2025-08-15) — "feat: stores 7 days worth of hourly energy usage". Predates the statistics importer.
- **Statistics importer introduced**: `ed94909` (2026-04-27) — "feat: v1.1.0 — Energy Dashboard integration + pymercury 1.1.0 compat". Wrote the daily-split logic without referencing the existing hourly cache — likely an oversight (no comment explaining the choice).
- **Implication**: The current behaviour is a long-standing gap, not a regression. Bumping to v1.3.0 captures it cleanly.

---

## Implementation Plan

### Step 1: Add a per-record hourly-bucket helper

**File**: `custom_components/mercury_co_nz/statistics.py`
**Lines**: insert a new static method between `_build_hourly_entries` (currently lines 150-232) and `async_update` (line 234)
**Action**: ADD

The existing `_build_hourly_entries` divides each daily total by `hours_in_day` (23/24/25). For real hourly records, each row IS one hour and must produce exactly one entry — no division.

**Add this helper:**

```python
@staticmethod
def _parse_hour_start_utc(record: dict[str, Any]) -> datetime | None:
    """Parse the start-of-hour UTC datetime for an hourly record.

    Hourly rows arrive with `'date'`/`'datetime'` as a full ISO timestamp
    (NZ-local with offset, e.g. `2026-04-25T14:00:00+12:00`). Both keys
    map to the same value for `extended_hourly_usage_history` rows
    (coordinator.py:454-456); raw `hourly_usage_history` rows only have
    `'date'`. Truncate to the hour boundary in UTC to match the daily-
    split slot grid exactly — this guarantees `async_add_external_statistics`
    upserts cleanly when a slot was previously written by the daily path.
    """
    raw = record.get("datetime") or record.get("date")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc = parsed.astimezone(timezone.utc)
    # Truncate to the hour to align with the daily-split grid.
    return utc.replace(minute=0, second=0, microsecond=0)
```

**Why**: Hourly rows from Mercury arrive at top-of-hour, but defensively truncating sub-hour precision avoids slot-misalignment that would cause both the daily-split entry AND the hourly entry to be retained for the same hour (double-count). Hour-aligned UTC keys are the recorder's idempotent upsert key.

---

### Step 2: Refactor `_build_hourly_entries` into a unified bucket-then-emit pipeline

**File**: `custom_components/mercury_co_nz/statistics.py`
**Lines**: 150-232 (replace the method)
**Action**: UPDATE

The new design: build a `dict[datetime_utc, tuple[float, float]]` keyed by hour-start UTC, populated FIRST from hourly records (real data wins), then daily-split fills in any uncovered NZ-local days. Emit entries in chronological order with one cumulative `sum` walk so the resulting series is strictly monotonic and idempotent under re-import.

**Current code** (`statistics.py:150-232`):

```python
@staticmethod
def _build_hourly_entries(
    records: list[dict[str, Any]],
    energy_sum_start: float,
    cost_sum_start: float,
    cutoff_ts: float,
) -> tuple[list[StatisticData], list[StatisticData], int]:
    """Split each daily record across 23/24/25 hourly StatisticData entries.
    ...
    """
    nz = ZoneInfo(NZ_TIMEZONE)
    energy_stats: list[StatisticData] = []
    cost_stats: list[StatisticData] = []
    null_skip_count = 0

    for record in records:
        consumption = record.get("consumption")
        cost = record.get("cost")
        # ... existing daily-split logic ...
        hourly_kwh = float(consumption) / hours_in_day
        hourly_cost = float(cost) / hours_in_day
        # ... emit hourly entries ...

    return energy_stats, cost_stats, null_skip_count
```

**Required change** — replace with:

```python
@staticmethod
def _build_hourly_entries(
    daily_records: list[dict[str, Any]],
    hourly_records: list[dict[str, Any]],
    energy_sum_start: float,
    cost_sum_start: float,
    cutoff_ts: float,
) -> tuple[list[StatisticData], list[StatisticData], int]:
    """Build hourly StatisticData entries, preferring real per-hour data.

    Hourly records are consumed verbatim — one input row produces exactly
    one output entry. Daily records are split across the actual NZ-local
    hour count (23/24/25, DST-aware) ONLY for hours not already covered
    by the hourly source. This means: recent days (within the hourly
    cache window) show a real consumption profile; older days outside
    that window fall back to the flat daily-split.

    Sums are accumulated in chronological order across the merged set so
    the series is strictly monotonic regardless of which source filled
    each bucket.
    """
    nz = ZoneInfo(NZ_TIMEZONE)
    null_skip_count = 0
    # hour_start_utc -> (kwh, cost)
    buckets: dict[datetime, tuple[float, float]] = {}

    # 1. Hourly records first — real data wins.
    for record in hourly_records or []:
        hour_start = MercuryStatisticsImporter._parse_hour_start_utc(record)
        if hour_start is None:
            null_skip_count += 1
            continue
        consumption = record.get("consumption")
        cost = record.get("cost")
        if consumption is None or cost is None:
            null_skip_count += 1
            continue
        buckets[hour_start] = (float(consumption), float(cost))

    # 2. Build the set of NZ-local dates that hourly records cover at all,
    #    so we can skip those days in the daily-split pass. We use NZ-local
    #    date because Mercury's daily records are NZ-day-aligned.
    hourly_covered_nz_dates: set[tuple[int, int, int]] = {
        (d := h.astimezone(nz)).year and (d.year, d.month, d.day)  # tuple key
        for h in buckets.keys()
    }

    # 3. Daily records — fill the gap for uncovered NZ-local days only.
    for record in daily_records or []:
        consumption = record.get("consumption")
        cost = record.get("cost")
        if consumption is None or cost is None:
            null_skip_count += 1
            continue
        raw = record.get("date")
        if not isinstance(raw, str):
            null_skip_count += 1
            continue
        try:
            parsed_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            null_skip_count += 1
            continue

        nz_date_key = (parsed_dt.year, parsed_dt.month, parsed_dt.day)
        if nz_date_key in hourly_covered_nz_dates:
            # Real hourly data already covers this day; do not double-fill.
            continue

        nz_midnight = datetime(
            parsed_dt.year, parsed_dt.month, parsed_dt.day, tzinfo=nz
        )
        next_nz_midnight = nz_midnight + timedelta(days=1)
        current_utc = nz_midnight.astimezone(timezone.utc)
        end_utc = next_nz_midnight.astimezone(timezone.utc)

        hours_in_day = 0
        probe = current_utc
        while probe < end_utc:
            hours_in_day += 1
            probe += timedelta(hours=1)
        if hours_in_day == 0:
            null_skip_count += 1
            continue

        hourly_kwh = float(consumption) / hours_in_day
        hourly_cost = float(cost) / hours_in_day

        slot = current_utc
        while slot < end_utc:
            buckets.setdefault(slot, (hourly_kwh, hourly_cost))
            slot += timedelta(hours=1)

    # 4. Emit chronologically with cumulative sums; skip slots before cutoff.
    energy_stats: list[StatisticData] = []
    cost_stats: list[StatisticData] = []
    for slot in sorted(buckets.keys()):
        if slot.timestamp() < cutoff_ts:
            continue
        kwh, cost_value = buckets[slot]
        energy_sum_start += kwh
        cost_sum_start += cost_value
        energy_stats.append(
            StatisticData(start=slot, state=kwh, sum=energy_sum_start)
        )
        cost_stats.append(
            StatisticData(start=slot, state=cost_value, sum=cost_sum_start)
        )

    return energy_stats, cost_stats, null_skip_count
```

**Why each piece**:

- **Buckets dict** — single source of truth for "what to emit at this hour-start". `buckets[slot] = ...` for hourly (overwrites if a stray duplicate appears in the input); `buckets.setdefault(slot, ...)` for daily so hourly always wins.
- **NZ-local date partition** — Mercury's daily records are NZ-day aligned. Two daily records for "yesterday" and "today" each cover their full NZ day in UTC slots; if hourly covers any part of "today", we skip the daily-split for the WHOLE NZ day to avoid mixing real and synthetic bins within a day (which would look jarring on the chart). Recent days within the 7-day (becoming 180-day) hourly window will be wholly real-hourly.
- **Walrus `(d := h.astimezone(nz)) and (d.year, ...)`**: the comprehension idiom is awkward; the implementer can split into two lines for clarity (use a regular `for` loop building the set).
- **Single sorted emission** — guarantees `sum` is monotonic regardless of input order.
- **Cutoff filter unchanged** — the existing 3-day re-import semantics are preserved.

---

### Step 3: Update `async_update` to pass both sources

**File**: `custom_components/mercury_co_nz/statistics.py`
**Lines**: 283-289 and 331-336
**Action**: UPDATE

**Current code** (`statistics.py:283-289`):

```python
# 3. Pull daily records (extended history preferred for backfill).
records = coordinator_data.get(
    "extended_daily_usage_history"
) or coordinator_data.get("daily_usage_history")
if not records:
    _LOGGER.debug("Mercury statistics: no daily records available; skipping")
    return
```

**Required change**:

```python
# 3. Pull daily records (extended history preferred for backfill) and
#    hourly records (real per-hour data, preferred over the daily split
#    for any NZ-local day they cover).
daily_records = coordinator_data.get(
    "extended_daily_usage_history"
) or coordinator_data.get("daily_usage_history") or []
hourly_records = coordinator_data.get(
    "extended_hourly_usage_history"
) or coordinator_data.get("hourly_usage_history") or []
if not daily_records and not hourly_records:
    _LOGGER.debug("Mercury statistics: no usage records available; skipping")
    return
```

**Current code** (`statistics.py:331-336`):

```python
energy_stats, cost_stats, null_skip_count = self._build_hourly_entries(
    records,
    last_sum_energy or 0.0,
    last_sum_cost or 0.0,
    cutoff_ts,
)
```

**Required change**:

```python
energy_stats, cost_stats, null_skip_count = self._build_hourly_entries(
    daily_records,
    hourly_records,
    last_sum_energy or 0.0,
    last_sum_cost or 0.0,
    cutoff_ts,
)
```

**Why**: Both lists now flow into the helper; `or []` guards keep the call shape stable when one source is absent (e.g., fresh install before hourly cache exists).

---

### Step 4: Refresh the importer's class docstring

**File**: `custom_components/mercury_co_nz/statistics.py`
**Lines**: 46-53
**Action**: UPDATE

**Current code**:

```python
class MercuryStatisticsImporter:
    """Push Mercury daily kWh + NZD costs into HA's long-term statistics table.

    Mercury's API delivers daily totals with a ~2-day delay. Live `total_increasing`
    sensors would freeze for 48h producing zero-kWh bins followed by a spike — wrong
    Energy Dashboard graphs. This class mirrors the Opower core integration's pattern:
    push external statistics directly to the recorder, backfilling up to 180 days on
    first run, re-importing the trailing few days each run to absorb bill corrections.
    """
```

**Required change**:

```python
class MercuryStatisticsImporter:
    """Push Mercury kWh + NZD costs into HA's long-term statistics table.

    Mercury's API exposes per-hour and per-day data with a ~2-day lag. Live
    `total_increasing` sensors would freeze for 48h producing zero-kWh bins
    followed by a spike. This class mirrors the Opower core integration's
    pattern: push external statistics directly to the recorder, backfilling
    up to 180 days on first run, re-importing the trailing few days each
    run to absorb bill corrections.

    For each NZ-local day, real per-hour values from `extended_hourly_usage_history`
    are emitted verbatim. Days not yet covered by the hourly cache fall back to
    the daily total split evenly across 23/24/25 hours (DST-aware).
    """
```

---

### Step 5: Extend hourly JSON cache retention to 180 days

**File**: `custom_components/mercury_co_nz/coordinator.py`
**Lines**: 195, 242-267, 437-438
**Action**: UPDATE

The current hourly cache caps at 7 days (`coordinator.py:245`). For the dashboard to keep a real-hourly profile for the same window the daily statistics cover, retention needs to match — 180 days. Each cache entry is small (~80 bytes JSON), so 180 days × 24 h ≈ 4320 entries ≈ ~350 KB on disk — acceptable.

**Current code** (`coordinator.py:194-195`):

```python
async def _store_hourly_data_json(self, data: dict[str, Any]) -> None:
    """Store cumulative hourly usage data in JSON file for 7-day history."""
```

**Required change**:

```python
async def _store_hourly_data_json(self, data: dict[str, Any]) -> None:
    """Store cumulative hourly usage data in JSON file (matches daily 180-day retention)."""
```

**Current code** (`coordinator.py:242-247`):

```python
            # Keep last 7 days (168 hours) to prevent unlimited growth
            # Use UTC time for consistent timezone handling
            now_utc = datetime.now(timezone.utc)
            cutoff_time = now_utc - timedelta(days=7)

                        # Filter to keep only last 7 days
            filtered_hourly_data = {}
```

**Required change**:

```python
            # Keep last STATISTICS_HOURLY_RETENTION_DAYS (matches daily 180-day cap
            # so the Energy Dashboard hourly profile matches the daily backfill window).
            now_utc = datetime.now(timezone.utc)
            cutoff_time = now_utc - timedelta(days=STATISTICS_HOURLY_RETENTION_DAYS)

            filtered_hourly_data = {}
```

**Current code** (`coordinator.py:265-267`):

```python
            if len(existing_hourly_data) != len(hourly_data):
                _LOGGER.info("Trimmed hourly data to last 7 days (was %d hours, now %d hours)",
                           len(existing_hourly_data), len(hourly_data))
```

**Required change**:

```python
            if len(existing_hourly_data) != len(hourly_data):
                _LOGGER.info(
                    "Trimmed hourly data to last %d days (was %d hours, now %d hours)",
                    STATISTICS_HOURLY_RETENTION_DAYS,
                    len(existing_hourly_data),
                    len(hourly_data),
                )
```

**Current code** (`coordinator.py:437-438`):

```python
    async def _load_extended_hourly_data(self) -> dict[str, Any]:
        """Load extended hourly data from JSON file to expose via sensors (7-day retention)."""
```

**Required change**:

```python
    async def _load_extended_hourly_data(self) -> dict[str, Any]:
        """Load extended hourly data from JSON file (matches daily 180-day retention)."""
```

Also check the `meta.retention_days` / `meta.retention_hours` fields written into the JSON file (around `coordinator.py:296-300` per the analyst report) and update them to the new constant — keeping them as literals is misleading once the retention changes.

---

### Step 6: Add the new constant

**File**: `custom_components/mercury_co_nz/const.py`
**Lines**: 333 (after `STATISTICS_BACKFILL_DAYS`)
**Action**: UPDATE

**Current code**:

```python
STATISTICS_BACKFILL_DAYS: Final[int] = 180  # matches the daily JSON retention cap
STATISTICS_REIMPORT_DAYS: Final[int] = 3  # always re-import last N days to absorb Mercury bill corrections
```

**Required change**:

```python
STATISTICS_BACKFILL_DAYS: Final[int] = 180  # matches the daily JSON retention cap
STATISTICS_HOURLY_RETENTION_DAYS: Final[int] = 180  # hourly cache retention; matches daily cap so Energy Dashboard hourly profile spans the same window
STATISTICS_REIMPORT_DAYS: Final[int] = 3  # always re-import last N days to absorb Mercury bill corrections
```

Then in `coordinator.py`'s import block (top of file), add `STATISTICS_HOURLY_RETENTION_DAYS` to the existing `from .const import (...)` statement.

---

### Step 7: Update tests

**File**: `custom_components/mercury_co_nz/tests/test_statistics.py`
**Action**: UPDATE

The existing tests pass `records` as a positional arg to `_build_hourly_entries`. The new signature takes `daily_records, hourly_records` as the first two positional args. Two changes:

**Change 1: Update existing tests' call sites** to pass `daily_records=records, hourly_records=[]`. There are calls at (per the test file structure) `test_hourly_split_normal_day_24_entries`, the DST tests (NZDT-start/end), the cutoff test, and the multi-record sum test. Each becomes:

```python
energy, cost, null = MercuryStatisticsImporter._build_hourly_entries(
    records,    # daily_records
    [],         # hourly_records — empty preserves daily-split behaviour
    0.0, 0.0, -1.0,
)
```

**Change 2: Add new tests** for the hourly path:

```python
def test_hourly_records_emit_one_entry_each() -> None:
    """One hourly record produces exactly one StatisticData entry (no division)."""
    hourly = [
        {"datetime": "2026-04-25T00:00:00+12:00", "consumption": 0.5, "cost": 0.10},
        {"datetime": "2026-04-25T01:00:00+12:00", "consumption": 0.7, "cost": 0.14},
        {"datetime": "2026-04-25T02:00:00+12:00", "consumption": 0.3, "cost": 0.06},
    ]
    energy, cost, null = MercuryStatisticsImporter._build_hourly_entries(
        [], hourly, 0.0, 0.0, -1.0,
    )
    assert len(energy) == 3
    assert len(cost) == 3
    assert null == 0
    # 2026-04-25 00:00 NZ (NZST = UTC+12) -> 2026-04-24 12:00 UTC.
    assert energy[0]["start"] == datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    assert energy[0]["state"] == pytest.approx(0.5)
    assert cost[0]["state"] == pytest.approx(0.10)
    # Cumulative sum follows raw values — no /24 division.
    assert energy[2]["sum"] == pytest.approx(1.5)
    assert cost[2]["sum"] == pytest.approx(0.30)


def test_hourly_overrides_daily_for_same_nz_day() -> None:
    """When hourly covers an NZ day, the daily record for that day is suppressed."""
    daily = [
        {"date": "2026-04-25T00:00:00", "consumption": 24.0, "cost": 12.0},  # would split to 1.0/0.5
        {"date": "2026-04-26T00:00:00", "consumption": 12.0, "cost": 6.0},   # not covered → split
    ]
    # One hourly point inside 2026-04-25 NZ-local day suppresses the whole daily record.
    hourly = [
        {"datetime": "2026-04-25T10:00:00+12:00", "consumption": 5.0, "cost": 2.5},
    ]
    energy, _cost, null = MercuryStatisticsImporter._build_hourly_entries(
        daily, hourly, 0.0, 0.0, -1.0,
    )
    assert null == 0
    # 1 hourly entry for 2026-04-25 + 24 daily-split entries for 2026-04-26 = 25.
    assert len(energy) == 25


def test_daily_only_path_unchanged_when_no_hourly() -> None:
    """Empty hourly_records preserves the original daily-split behaviour exactly."""
    daily = [{"date": "2026-05-15T00:00:00", "consumption": 24.0, "cost": 12.0}]
    energy, cost, null = MercuryStatisticsImporter._build_hourly_entries(
        daily, [], 0.0, 0.0, -1.0,
    )
    assert len(energy) == 24
    assert energy[0]["state"] == pytest.approx(1.0)
    assert cost[0]["state"] == pytest.approx(0.5)
    assert null == 0


def test_merged_sums_strictly_monotonic() -> None:
    """Cumulative sum is monotonic across mixed daily-split + hourly entries."""
    daily = [{"date": "2026-04-23T00:00:00", "consumption": 24.0, "cost": 12.0}]
    hourly = [
        {"datetime": "2026-04-25T10:00:00+12:00", "consumption": 0.5, "cost": 0.10},
        {"datetime": "2026-04-25T11:00:00+12:00", "consumption": 0.7, "cost": 0.14},
    ]
    energy, _cost, _null = MercuryStatisticsImporter._build_hourly_entries(
        daily, hourly, 0.0, 0.0, -1.0,
    )
    # Entries appear in chronological order; sums increase monotonically.
    sums = [e["sum"] for e in energy]
    assert sums == sorted(sums)
    assert all(b > a for a, b in zip(sums, sums[1:]))
```

---

### Step 8: Update README

**File**: `README.md`
**Lines**: ~93 (the "Notes" bullet)
**Action**: UPDATE

**Current text:**

> - Mercury provides daily-resolution data only; the integration spreads each daily total across 23/24/25 hourly bins (DST-aware) so the dashboard hourly view shows a smooth profile rather than a single midnight spike.

**Required change:**

> - Mercury exposes per-hour usage in addition to daily totals. The integration prefers real per-hour values for the dashboard hourly view; days outside the hourly cache window fall back to a daily-total split evenly across 23/24/25 hours (DST-aware), so the trailing 180-day backfill is still smooth even before the hourly cache has filled.

---

### Step 9: Bump version

**File**: `custom_components/mercury_co_nz/manifest.json`
**Action**: UPDATE
**Line 13**: `"version": "1.2.4"` → `"version": "1.3.0"` (minor — Energy Dashboard fidelity improvement; no schema change).

---

## Patterns to Follow

**Cumulative sum walk** — the existing pattern at `statistics.py:214-215` already accumulates `energy_sum_start` and `cost_sum_start` across the outer loop. The new helper preserves this idiom; only the iteration order is changed (`for slot in sorted(buckets.keys())` instead of `for record in records`).

**Idempotent upsert via `start` key** — the existing dependency on `async_add_external_statistics`'s upsert-on-`start` semantics is preserved. The hour-truncation in `_parse_hour_start_utc` (`utc.replace(minute=0, second=0, microsecond=0)`) keeps slot keys aligned with the daily-split grid so swaps are seamless on subsequent imports.

**3-day re-import cutoff** — left untouched. Each cycle re-emits the trailing 3 days; bill corrections from Mercury arriving on day-2-since-event are absorbed automatically. This mechanism now also auto-promotes synthetic-split entries to real-hourly entries the moment hourly data arrives for that day.

---

## Edge Cases & Risks

| Risk / Edge Case                                                                              | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Hourly cost field is missing or zero                                                          | `_execute_api_call_with_fallback` defaults `cost` to `0` when absent (`coordinator.py:237`). The new helper checks `cost is None` and skips, so explicit `None` is dropped, but `cost == 0.0` (default fallback) WOULD be emitted as a real zero — wrong if Mercury's hourly endpoint genuinely lacks cost. **Mitigation**: in `_build_hourly_entries`, treat hourly rows with `cost == 0` as "cost-unknown" and use `daily_total / 24` as a proxy when a same-NZ-day daily record exists. (Or accept the zero — verify by inspecting one cycle of `mercury_hourly.json` after deploy; if cost is uniformly zero, add the proxy.) |
| Existing recorder rows for days now covered by hourly                                         | `async_add_external_statistics` upserts on `start`. Hour-aligned slots from the new pipeline overwrite the old daily-split rows in-place. The 3-day re-import cutoff guarantees the trailing 3 days are always re-emitted, so within ~3 update cycles after deploy, the visible part of the dashboard converges. Older days (>3) keep their pre-existing daily-split values until the next backfill window covers them — acceptable.                                                                                                                                                                                              |
| Day partially covered by hourly (e.g., crash mid-day or fresh install with 2-day API window)  | `hourly_covered_nz_dates` uses ANY hourly point in a given NZ day to suppress the daily-split. With only 1 hourly point, that day will have ONE real bin and 22-24 missing bins — gappy chart. **Decision**: this is correct because mixing real (2 kWh between 14:00-15:00) and synthetic (avg between 00:00-13:00) within a day distorts both. A gap is a clearer signal than a misleading flat profile. The 5-min poll fills the rest within ~24h.                                                                                                                                                                              |
| Hourly cache jumping from 7 → 180 days on existing installs                                   | The retention bump only affects how long entries live, not the entry shape. Existing JSON files load fine; new entries accumulate up to 180 days going forward. No migration required.                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| DST transition within the hourly window                                                       | Hourly records arrive with their NZ-local offset (`+12:00` or `+13:00`) embedded in the `date`/`datetime` field. After `astimezone(timezone.utc)`, two distinct hourly slots that share a wall-clock label (e.g., 02:00 and 02:00 on DST-end) become two distinct UTC slots, so neither is lost. Verified by the round-trip in `_parse_hour_start_utc`.                                                                                                                                                                                                                                                                              |
| Backwards compatibility — `_build_hourly_entries` signature change                            | The method is `@staticmethod` and only called from `async_update` (one site, in the same file) and from the test suite. No external imports. Updating both call sites is a closed change.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Sum drift across deploy boundary                                                              | The cumulative `sum` is anchored to `last_sum_energy` / `last_sum_cost` from `get_last_statistics` (`statistics.py:320-325`). The next emission picks up where the recorder last saw the series. Switching from synthetic to real bins WILL produce slightly different `state` per hour but `sum` continues to grow monotonically — what the dashboard chart cares about. No special handling needed.                                                                                                                                                                                                                              |
| Frontend cards regression                                                                     | Confirmed: all three custom cards read sensor entity attributes directly, never the recorder. Out of scope; no card change needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

---

## Validation

### Automated Checks

```bash
# From repository root.
pytest custom_components/mercury_co_nz/tests/test_statistics.py -v
pytest custom_components/mercury_co_nz/tests/ -v   # full suite — none of the others touch statistics
python -m py_compile custom_components/mercury_co_nz/statistics.py
python -m py_compile custom_components/mercury_co_nz/coordinator.py
python -m py_compile custom_components/mercury_co_nz/const.py
```

### Manual Verification

1. Deploy the change to a HA instance with an existing 7+ day install (so the hourly cache is non-empty).
2. Restart HA. Wait one coordinator cycle (~5 minutes).
3. Open **Settings → Dashboards → Energy → Hourly view** for today and yesterday.
4. **Expected**: hourly bars now show distinct heights matching the user's actual usage pattern (morning spike, evening peak), not 24 identical bars.
5. Switch to the daily view: total per day should be unchanged (sum-of-hourly = old daily-split total, modulo the small drift from real distribution vs flat).
6. Look 8+ days back (outside the current hourly cache window): bars should still be flat — daily-split fallback kicked in. Over time as the 180-day hourly cache fills, this region transitions to real-hourly.
7. Tail HA logs and confirm: `"Mercury statistics: imported N hourly entries"` log line; no `null_skipped > 7` warnings; no recorder errors.
8. Run `python -c "import json; d=json.load(open('/config/www/mercury_hourly.json')); print(len(d['hourly_usage']), 'entries')"` — value should be growing past 168 each day.

---

## Scope Boundaries

**IN SCOPE:**

- `statistics.py`: new `_parse_hour_start_utc` helper, refactored `_build_hourly_entries`, updated `async_update` call sites and docstring.
- `coordinator.py`: hourly cache retention bumped from 7 to 180 days via the new constant.
- `const.py`: new `STATISTICS_HOURLY_RETENTION_DAYS` constant.
- `tests/test_statistics.py`: signature updates + four new test cases.
- `README.md`: one-line correction to the daily-resolution claim.
- `manifest.json`: version bump 1.2.4 → 1.3.0.

**OUT OF SCOPE (do not touch):**

- Sensor entity attributes / chart-attribute truncation (`sensor.py:264-309`, `const.py:CHART_ATTRIBUTE_*`) — independent code path.
- Custom Lovelace cards (`energy-usage-card.js`, `energy-monthly-summary-card.js`, `energy-weekly-summary-card.js`) — they read sensor attributes, not statistics, and are unaffected.
- Mercury bill corrections handling — already absorbed by the existing 3-day re-import window; no change needed.
- The `STATISTICS_BACKFILL_DAYS` constant — defined but unused; do not start using it as part of this change (separate cleanup).
- Daily JSON cache (`mercury_daily.json`) and `_store_daily_data_json` — already at 180 days; unchanged.
- TOU plan support / multi-rate hourly costs — Mercury's hourly cost handling is opaque; treat per-hour cost as opaque numeric and pass through. Multi-rate plans are explicitly deferred per README.
- pymercury upgrade — current `>=1.1.0` is sufficient; the hourly endpoint is already exercised.
- Energy Dashboard config flow / setup steps — unchanged.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-26T19:33:08Z
- **Artifact**: `.claude/PRPs/issues/investigation-20260426T193308Z.md`
- **Implementation entry point**: `/prp-issue-fix .claude/PRPs/issues/investigation-20260426T193308Z.md`
