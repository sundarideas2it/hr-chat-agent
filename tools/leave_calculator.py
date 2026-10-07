"""Deterministic leave-day count from the supplied leave policy.

Section 7.3 of Revised Leave Policy - I2I.pdf says a public holiday or a
weekly off inside an approved leave period is not counted as leave. Holiday
dates come from the SQLite holidays table, loaded from Holiday List - 2026.pdf.
Saturday and Sunday are weekly offs because the office is closed on those days.
This function does not call Gemini.
"""

from __future__ import annotations

from datetime import timedelta

from tools.errors import LeaveToolError
from tools.holidays import get_holidays_between, parse_iso_date
from tools.policy_rules import (
    HOLIDAY_DATA_WARNING,
    HOLIDAY_RULE,
    WEEKLY_OFF_RULE,
)


def calculate_leave_days(start_date: str, end_date: str) -> dict:
    """Count chargeable leave days from start through end, inclusive."""
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if start > end:
        raise LeaveToolError("The end date must be on or after the start date.")

    holiday_names = {
        holiday["holiday_date"]: holiday["name"]
        for holiday in get_holidays_between(start, end)
    }
    excluded: list[dict] = []
    day = start
    while day <= end:
        iso = day.isoformat()
        if iso in holiday_names:
            excluded.append(
                {"date": iso, "reason": "public holiday", "name": holiday_names[iso]}
            )
        elif day.weekday() >= 5:
            excluded.append(
                {
                    "date": iso,
                    "reason": "weekly off",
                    "name": "Saturday" if day.weekday() == 5 else "Sunday",
                }
            )
        day += timedelta(days=1)

    calendar_days = (end - start).days + 1
    applied = []
    if any(item["reason"] == "public holiday" for item in excluded):
        applied.append(HOLIDAY_RULE)
    if any(item["reason"] == "weekly off" for item in excluded):
        applied.append(WEEKLY_OFF_RULE)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "calendar_days": calendar_days,
        "chargeable_leave_days": calendar_days - len(excluded),
        "excluded_dates": excluded,
        "applied_rules": applied,
        "warnings": [HOLIDAY_DATA_WARNING],
    }
