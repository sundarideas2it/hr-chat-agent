"""SQLite database access for employees and leave records.

The database file is ``database/hr_chat.db``. Connections enable foreign
keys. Password hashes are created with PBKDF2; plaintext passwords are
never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "hr_chat.db"

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 200_000
_HASH_PREFIX = "pbkdf2_sha256"

# Returned to the application after a successful login. ``password_hash``
# is intentionally absent.
PUBLIC_EMPLOYEE_FIELDS = (
    "id",
    "employee_code",
    "name",
    "email",
    "department",
    "joining_date",
    "employment_type",
    "is_active",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY,
    employee_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    department TEXT,
    joining_date TEXT,
    employment_type TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS leave_types (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    annual_entitlement INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS leave_balances (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    leave_type_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    entitled REAL NOT NULL,
    used REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (leave_type_id) REFERENCES leave_types(id),
    UNIQUE (employee_id, leave_type_id, year)
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    leave_type_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    days REAL NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (leave_type_id) REFERENCES leave_types(id),
    UNIQUE (employee_id, leave_type_id, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS holidays (
    id INTEGER PRIMARY KEY,
    holiday_date TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL
);
"""


def hash_password(password: str) -> str:
    """Return a salted PBKDF2 hash string. The password is not retained."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return f"{_HASH_PREFIX}${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True when ``password`` matches a hash from ``hash_password``."""
    try:
        prefix, iterations, salt, digest = stored_hash.split("$")
        iteration_count = int(iterations)
    except (AttributeError, ValueError):
        return False
    if prefix != _HASH_PREFIX or iteration_count < 1 or not salt or not digest:
        return False
    computed = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iteration_count,
    )
    return hmac.compare_digest(computed.hex(), digest)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Open the HR database with row access and foreign keys enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create tables if they do not already exist."""
    with get_connection() as connection:
        connection.executescript(_SCHEMA)


def get_public_employee(employee_id: int) -> dict | None:
    """Return the public profile for an active employee id."""
    if isinstance(employee_id, bool) or not isinstance(employee_id, int):
        return None
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, employee_code, name, email, department,
                   joining_date, employment_type, is_active
            FROM employees
            WHERE id = ? AND is_active = 1
            """,
            (employee_id,),
        ).fetchone()
    if row is None:
        return None
    return {field: row[field] for field in PUBLIC_EMPLOYEE_FIELDS}


def authenticate(employee_code: str, password: str) -> dict | None:
    """Return the signed-in employee, or None when the credentials fail.

    The returned mapping includes the internal employee id and excludes
    ``password_hash``. Callers must keep this mapping in the application
    session and must not accept a different employee id from the user.
    """
    code = employee_code.strip()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, employee_code, name, email, password_hash, department,
                   joining_date, employment_type, is_active
            FROM employees
            WHERE employee_code = ? AND is_active = 1
            """,
            (code,),
        ).fetchone()

    stored_hash = row["password_hash"] if row is not None else _unknown_user_hash()
    password_matches = verify_password(password, stored_hash)
    if row is None or not password_matches:
        return None

    return {field: row[field] for field in PUBLIC_EMPLOYEE_FIELDS}


def _unknown_user_hash() -> str:
    """Stable dummy hash so a missing employee still runs PBKDF2."""
    global _UNKNOWN_USER_HASH
    if _UNKNOWN_USER_HASH is None:
        _UNKNOWN_USER_HASH = hash_password("unknown-user")
    return _UNKNOWN_USER_HASH


_UNKNOWN_USER_HASH: str | None = None
