"""Idempotent demo data for the local HR database.

Running this module again updates the canonical leave types, balances, and
requests. It does not recreate employees who are already present.

Annual entitlements for CL, SL, and EL come from Revised Leave Policy -
I2I.pdf (6, 6, and 12 days). Privilege Leave has no annual grant in that
policy, so PL balances below are sample retained amounts. Used days are
sample database data in every case.
"""

from __future__ import annotations

from database.db import get_connection, hash_password, init_db

DEMO_PASSWORD = "Demo@123"

_EMPLOYEES = (
    {
        "employee_code": "EMP001",
        "name": "Arun Kumar",
        "email": "arun.kumar@example.com",
        "department": "Engineering",
        "joining_date": "2021-04-12",
        "employment_type": "Full-time",
    },
    {
        "employee_code": "EMP002",
        "name": "Priya Sharma",
        "email": "priya.sharma@example.com",
        "department": "Finance",
        "joining_date": "2022-08-01",
        "employment_type": "Full-time",
    },
    {
        "employee_code": "EMP003",
        "name": "Rahul Verma",
        "email": "rahul.verma@example.com",
        "department": "HR",
        "joining_date": "2019-11-15",
        "employment_type": "Full-time",
    },
)

# code, name, annual entitlement.
# CL/SL/EL quotas are stated in the PDF. PL is 0 because the PDF does not
# grant a yearly Privilege Leave entitlement.
_LEAVE_TYPES = (
    ("CL", "Casual Leave", 6),
    ("SL", "Sick Leave", 6),
    ("EL", "Earned Leave", 12),
    ("PL", "Privilege Leave", 0),
)

# entitled, used for calendar year 2026.
# CL/SL/EL entitled values match the PDF. PL entitled values are sample
# retained balances, not a policy annual quota. Used values are sample data.
_BALANCES = {
    "EMP001": {"CL": (6, 2), "SL": (6, 2), "EL": (12, 0), "PL": (6, 4)},
    "EMP002": {"CL": (6, 3), "SL": (6, 0), "EL": (12, 0), "PL": (6, 0)},
    "EMP003": {"CL": (6, 1), "SL": (6, 0), "EL": (12, 0), "PL": (6, 5)},
}

_LEAVE_REQUESTS = (
    ("EMP001", "CL", "2026-02-09", "2026-02-10", 2, "approved"),
    ("EMP001", "SL", "2026-03-04", "2026-03-05", 2, "approved"),
    ("EMP001", "PL", "2026-06-08", "2026-06-11", 4, "approved"),
    ("EMP002", "CL", "2026-04-06", "2026-04-08", 3, "approved"),
    ("EMP003", "PL", "2026-09-14", "2026-09-18", 5, "approved"),
)

# Earlier demo rows that contradict the canonical requests above.
_OBSOLETE_REQUESTS = (
    ("EMP001", "CL", "2026-02-09", "2026-02-13"),
)

_HOLIDAYS = (
    ("2026-01-01", "New Year's Day"),
    ("2026-01-26", "Republic Day"),
    ("2026-05-01", "Labour Day"),
    ("2026-08-15", "Independence Day"),
    ("2026-10-02", "Gandhi Jayanti"),
    ("2026-12-25", "Christmas"),
)


def seed() -> None:
    """Insert missing demo rows and refresh canonical leave figures."""
    init_db()
    with get_connection() as connection:
        for code, name, entitlement in _LEAVE_TYPES:
            connection.execute(
                """
                INSERT INTO leave_types (code, name, annual_entitlement)
                VALUES (?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    annual_entitlement = excluded.annual_entitlement
                """,
                (code, name, entitlement),
            )

        existing_codes = {
            row["employee_code"]
            for row in connection.execute("SELECT employee_code FROM employees")
        }
        missing_employees = [
            employee
            for employee in _EMPLOYEES
            if employee["employee_code"] not in existing_codes
        ]
        for employee in missing_employees:
            connection.execute(
                """
                INSERT INTO employees (
                    employee_code, name, email, password_hash, department,
                    joining_date, employment_type, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    employee["employee_code"],
                    employee["name"],
                    employee["email"],
                    hash_password(DEMO_PASSWORD),
                    employee["department"],
                    employee["joining_date"],
                    employee["employment_type"],
                ),
            )

        employee_ids = {
            row["employee_code"]: row["id"]
            for row in connection.execute("SELECT id, employee_code FROM employees")
        }
        leave_type_ids = {
            row["code"]: row["id"]
            for row in connection.execute("SELECT id, code FROM leave_types")
        }

        for employee_code, balances in _BALANCES.items():
            for leave_code, (entitled, used) in balances.items():
                connection.execute(
                    """
                    INSERT INTO leave_balances (
                        employee_id, leave_type_id, year, entitled, used
                    )
                    VALUES (?, ?, 2026, ?, ?)
                    ON CONFLICT(employee_id, leave_type_id, year) DO UPDATE SET
                        entitled = excluded.entitled,
                        used = excluded.used
                    """,
                    (
                        employee_ids[employee_code],
                        leave_type_ids[leave_code],
                        entitled,
                        used,
                    ),
                )

        for employee_code, leave_code, start, end in _OBSOLETE_REQUESTS:
            connection.execute(
                """
                DELETE FROM leave_requests
                WHERE employee_id = ?
                  AND leave_type_id = ?
                  AND start_date = ?
                  AND end_date = ?
                """,
                (
                    employee_ids[employee_code],
                    leave_type_ids[leave_code],
                    start,
                    end,
                ),
            )

        for employee_code, leave_code, start, end, days, status in _LEAVE_REQUESTS:
            connection.execute(
                """
                INSERT INTO leave_requests (
                    employee_id, leave_type_id, start_date, end_date, days, status
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, leave_type_id, start_date, end_date)
                DO UPDATE SET
                    days = excluded.days,
                    status = excluded.status
                """,
                (
                    employee_ids[employee_code],
                    leave_type_ids[leave_code],
                    start,
                    end,
                    days,
                    status,
                ),
            )

        for holiday_date, name in _HOLIDAYS:
            connection.execute(
                """
                INSERT INTO holidays (holiday_date, name)
                VALUES (?, ?)
                ON CONFLICT(holiday_date) DO NOTHING
                """,
                (holiday_date, name),
            )


def main() -> None:
    seed()


if __name__ == "__main__":
    main()
