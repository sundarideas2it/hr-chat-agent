"""Leave balance and history for one signed-in employee.

Callers must pass the internal employee id from the application session.
These functions do not accept an employee code.
"""

from __future__ import annotations

import sqlite3

from database.db import get_connection
from tools.errors import LeaveToolError
from tools.policy_rules import DEFAULT_LEAVE_YEAR, LEAVE_TYPE_NOTES


def get_leave_balance(
    employee_id: int,
    leave_type_code: str | None = None,
    year: int | None = None,
) -> dict:
    """Return entitled, used, and remaining leave for one employee."""
    employee = _require_employee(employee_id)
    leave_year = _require_year(year)
    code = _normalize_code(leave_type_code) if leave_type_code else None
    if code is not None:
        _require_leave_type(code)

    try:
        with get_connection() as connection:
            query = """
                SELECT lt.code, lt.name, b.entitled, b.used
                FROM leave_balances b
                JOIN leave_types lt ON lt.id = b.leave_type_id
                WHERE b.employee_id = ? AND b.year = ?
            """
            params: list[object] = [employee["id"], leave_year]
            if code is not None:
                query += " AND lt.code = ?"
                params.append(code)
            query += " ORDER BY lt.code"
            rows = connection.execute(query, params).fetchall()
            balances = [_balance_row(row) for row in rows]
    except sqlite3.Error as exc:
        raise LeaveToolError("The leave balance could not be read.") from exc

    if code is not None and not balances:
        raise LeaveToolError(
            f"No {code} balance is recorded for this employee in {leave_year}."
        )

    return {
        "employee_code": employee["employee_code"],
        "year": leave_year,
        "balances": balances,
    }


def get_leave_history(employee_id: int, year: int | None = None) -> dict:
    """Return leave requests for one employee, and no one else."""
    employee = _require_employee(employee_id)
    leave_year = _require_year(year)
    try:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT lt.code, lt.name, r.start_date, r.end_date, r.days, r.status
                FROM leave_requests r
                JOIN leave_types lt ON lt.id = r.leave_type_id
                WHERE r.employee_id = ?
                  AND r.start_date >= ?
                  AND r.start_date <= ?
                ORDER BY r.start_date, lt.code
                """,
                (
                    employee["id"],
                    f"{leave_year}-01-01",
                    f"{leave_year}-12-31",
                ),
            ).fetchall()
            requests = [
                {
                    "leave_type": row["code"],
                    "leave_name": row["name"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "days": _number(row["days"]),
                    "status": row["status"],
                }
                for row in rows
            ]
    except sqlite3.Error as exc:
        raise LeaveToolError("The leave history could not be read.") from exc

    return {
        "employee_code": employee["employee_code"],
        "year": leave_year,
        "requests": requests,
    }


def list_leave_types() -> list[dict]:
    """Return leave types for display. This is not employee data."""
    try:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT code, name, annual_entitlement
                FROM leave_types
                ORDER BY code
                """
            ).fetchall()
            leave_types = [
                {
                    "code": row["code"],
                    "name": row["name"],
                    "annual_entitlement": _number(row["annual_entitlement"]),
                }
                for row in rows
            ]
    except sqlite3.Error as exc:
        raise LeaveToolError("The leave types could not be read.") from exc
    return leave_types


def _require_employee(employee_id: int) -> sqlite3.Row:
    if isinstance(employee_id, bool) or not isinstance(employee_id, int):
        raise LeaveToolError(
            "employee_id must be the internal id from the signed-in session."
        )
    try:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, employee_code
                FROM employees
                WHERE id = ? AND is_active = 1
                """,
                (employee_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise LeaveToolError("The employee record could not be read.") from exc
    if row is None:
        raise LeaveToolError("No active employee matches the signed-in session.")
    return {"id": row["id"], "employee_code": row["employee_code"]}


def _require_leave_type(code: str) -> None:
    try:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT id FROM leave_types WHERE code = ?",
                (code,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise LeaveToolError("The leave type could not be read.") from exc
    if row is None:
        raise LeaveToolError(f"Unknown leave type '{code}'.")


def _require_year(year: int | None) -> int:
    if year is None:
        return DEFAULT_LEAVE_YEAR
    if isinstance(year, bool) or not isinstance(year, int):
        raise LeaveToolError("Year must be a four-digit number.")
    if year < 1900 or year > 9999:
        raise LeaveToolError("Year must be a four-digit number.")
    return year


def _normalize_code(leave_type_code: str) -> str:
    if not isinstance(leave_type_code, str) or not leave_type_code.strip():
        raise LeaveToolError("Unknown leave type.")
    return leave_type_code.strip().upper()


def _balance_row(row: sqlite3.Row) -> dict:
    entitled = _number(row["entitled"])
    used = _number(row["used"])
    remaining = _number(float(row["entitled"]) - float(row["used"]))
    item = {
        "leave_type": row["code"],
        "leave_name": row["name"],
        "entitled": entitled,
        "used": used,
        "remaining": remaining,
    }
    note = LEAVE_TYPE_NOTES.get(row["code"])
    if note:
        item["note"] = note
    return item


def _number(value: object) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number
