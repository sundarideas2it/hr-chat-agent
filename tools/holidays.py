"""Holiday lookup against the SQLite holidays table."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from database.db import get_connection
from tools.errors import LeaveToolError


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
