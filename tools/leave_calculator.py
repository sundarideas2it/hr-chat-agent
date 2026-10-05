"""Deterministic leave-day count from the supplied leave policy.

Section 7.3 of Revised Leave Policy - I2I.pdf says a public holiday or a
weekly off inside an approved leave period is not counted as leave. The PDF
does not define which weekdays are weekly offs, so this function excludes
only holidays stored in SQLite and reports that limit.
"""

from __future__ import annotations

from tools.errors import LeaveToolError
from tools.holidays import get_holidays_between, parse_iso_date
from tools.policy_rules import HOLIDAY_DATA_WARNING, HOLIDAY_RULE, WEEKLY_OFF_WARNING


def calculate_leave_days(start_date: str, end_date: str) -> dict:
    """Count chargeable leave days from start through end, inclusive."""
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if start > end:
        raise LeaveToolError("The end date must be on or after the start date.")

    holidays = get_holidays_between(start, end)
    excluded = [
        {
            "date": holiday["holiday_date"],
            "reason": "public holiday",
            "name": holiday["name"],
        }
        for holiday in holidays
    ]
    calendar_days = (end - start).days + 1
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "calendar_days": calendar_days,
        "chargeable_leave_days": calendar_days - len(excluded),
        "excluded_dates": excluded,
        "applied_rules": [HOLIDAY_RULE],
        "warnings": [WEEKLY_OFF_WARNING, HOLIDAY_DATA_WARNING],
    }
