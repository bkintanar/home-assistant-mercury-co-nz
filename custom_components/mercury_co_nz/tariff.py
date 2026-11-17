"""Explicit, per-meter day/night classification; never infer a billing schedule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
from zoneinfo import ZoneInfo

CONF_TARIFF_SCHEDULES = "tariff_schedules"
UTC = timezone.utc


@dataclass(frozen=True)
class Schedule:
    night_start: int
    night_end: int
    start_date: date
    time_zone: str = "Pacific/Auckland"
    weekend_night: bool = False

    @classmethod
    def from_options(cls, options):
        if not options or not options.get("enabled"):
            return None

        # Source samples cover whole hours. A half-hour boundary cannot be
        # split accurately, so reject it rather than prorating consumption.
        def hour(value):
            if not isinstance(value, str) or len(value) != 5 or value[2:] != ":00":
                raise ValueError("Use whole-hour boundaries")
            result = int(value[:2])
            if not 0 <= result <= 23:
                raise ValueError("Invalid hour")
            return result

        start, end = hour(options["night_start"]), hour(options["night_end"])
        if start == end:
            raise ValueError("Day and night must both have nonzero duration")
        zone = options.get("time_zone", "Pacific/Auckland")
        if zone not in ("Pacific/Auckland", "Etc/GMT-12"):
            raise ValueError("Unsupported time basis")
        weekend = options.get("weekend_night", False)
        if not isinstance(weekend, bool):
            raise ValueError("Invalid weekend option")
        return cls(start, end, date.fromisoformat(options["start_date"]), zone, weekend)

    @property
    def key(self):
        # A changed schedule gets a separate series; never silently reinterpret
        # old statistics or leave stale bins from the old schedule in a new one.
        value = (
            f"{self.night_start}:{self.night_end}:{self.start_date}:{self.time_zone}"
        )
        # Preserve IDs for all existing daily schedules.
        if self.weekend_night:
            value += ":weekend_night"
        return hashlib.sha256(value.encode()).hexdigest()[:12]

    def period(self, stamp):
        local = stamp.astimezone(ZoneInfo(self.time_zone))
        if local.date() < self.start_date:
            return None
        if self.weekend_night and local.weekday() >= 5:
            return "night"
        h = local.hour
        night = (
            self.night_start <= h < self.night_end
            if self.night_start < self.night_end
            else h >= self.night_start or h < self.night_end
        )
        return "night" if night else "day"


def normalize_hours(records):
    """Validate actual hourly samples, preserving gaps and both autumn folds."""
    hours = {}
    for row in records:
        try:
            stamp = datetime.fromisoformat(
                (row.get("datetime") or row["date"]).replace("Z", "+00:00")
            )
            quantity = row.get("consumption", row.get("usage"))
            if (
                stamp.tzinfo is None
                or stamp.minute
                or stamp.second
                or stamp.microsecond
                or isinstance(quantity, bool)
                or not isinstance(quantity, (int, float))
                or not math.isfinite(quantity)
                or quantity < 0
            ):
                continue
            # Mercury sometimes emits a fictional 02:00+12:00 at spring DST.
            # Reject that placeholder without overwriting the real 03:00+13:00.
            if stamp.utcoffset() in (timedelta(hours=12), timedelta(hours=13)):
                if stamp.astimezone(ZoneInfo("Pacific/Auckland")).replace(
                    tzinfo=None
                ) != stamp.replace(tzinfo=None):
                    continue
            hours[str(int(stamp.timestamp()))] = {
                "consumption": quantity,
                "is_estimated": row.get("is_estimated"),
                "read_type": row.get("read_type"),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return hours


def build_breakdown(hours, schedule):
    """Return cumulative day/night series from recorded hours."""
    series = {"day": [], "night": []}
    totals = {"day": Decimal(0), "night": Decimal(0)}
    for epoch, value in sorted(hours.items(), key=lambda item: int(item[0])):
        stamp = datetime.fromtimestamp(int(epoch), UTC)
        period = schedule.period(stamp)
        if period is None:
            continue
        totals[period] += Decimal(str(value["consumption"]))
        for name in series:
            series[name].append(
                {
                    "start": stamp,
                    "state": float(totals[name]),
                    "sum": float(totals[name]),
                }
            )
    return series


def fingerprint(hours, schedule):
    return hashlib.sha256(
        json.dumps([hours, schedule.key], sort_keys=True).encode()
    ).hexdigest()
