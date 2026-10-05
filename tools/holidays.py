"""Holiday lookup against the SQLite holidays table.

The rows are the official 2026 dates from Holiday List - 2026.pdf.
These functions do not call Gemini.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from database.db import get_connection
from tools.errors import LeaveToolError
from tools.policy_rules import DEFAULT_LEAVE_YEAR, HOLIDAY_LIST_DOCUMENT

HOLIDAY_LIST_SOURCE = HOLIDAY_LIST_DOCUMENT


def get_holidays_between(start_date: str | date, end_date: str | date) -> list[dict]:
    """Return holidays on or between the two dates, inclusive."""
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if start > end:
        raise LeaveToolError("The end date must be on or after the start date.")

    try:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT holiday_date, name
                FROM holidays
                WHERE holiday_date >= ? AND holiday_date <= ?
                ORDER BY holiday_date
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            holidays = [
                {"holiday_date": row["holiday_date"], "name": row["name"]}
                for row in rows
            ]
    except sqlite3.Error as exc:
        raise LeaveToolError("The holiday list could not be read.") from exc

    return holidays


def get_holidays(year: int | None = None, month: int | None = None) -> dict:
    """Return company holidays for a calendar year, or for one month of that year."""
    leave_year = _require_year(year)
    leave_month = _require_month(month)
    if leave_month is None:
        start = date(leave_year, 1, 1)
        end = date(leave_year, 12, 31)
    else:
        start = date(leave_year, leave_month, 1)
        if leave_month == 12:
            end = date(leave_year, 12, 31)
        else:
            end = date(leave_year, leave_month + 1, 1) - timedelta(days=1)
    rows = get_holidays_between(start, end)
    return {
        "year": leave_year,
        "month": leave_month,
        "source": HOLIDAY_LIST_SOURCE,
        "holidays": [{"date": row["holiday_date"], "name": row["name"]} for row in rows],
    }


def _require_year(year: int | None) -> int:
    if year is None:
        return DEFAULT_LEAVE_YEAR
    if isinstance(year, bool) or not isinstance(year, int) or year < 1900 or year > 9999:
        raise LeaveToolError("Year must be a four-digit number.")
    return year


def _require_month(month: int | None) -> int | None:
    if month is None:
        return None
    if isinstance(month, bool) or not isinstance(month, int) or month < 1 or month > 12:
        raise LeaveToolError("Month must be a number from 1 to 12.")
    return month


def parse_iso_date(value: str | date | datetime) -> date:
    """Accept a date or a YYYY-MM-DD string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise LeaveToolError("Dates must be ISO dates in YYYY-MM-DD form.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise LeaveToolError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc
    if parsed.isoformat() != value:
        raise LeaveToolError(f"Invalid date '{value}'. Use YYYY-MM-DD.")
    return parsed
