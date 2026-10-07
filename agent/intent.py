"""Choose a tool path from the employee message and recent session turns.

This step is deterministic so a database question can be answered without
calling Gemini. It never returns another employee's id.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from database.db import get_connection
from tools.errors import LeaveToolError
from tools.policy_rules import DEFAULT_LEAVE_YEAR

_HISTORY = re.compile(
    r"\b(leave history|my history|past leave|previous leaves|leave requests|"
    r"leaves i took|leaves have i taken|leaves i have taken)\b",
    re.IGNORECASE,
)
_ELIGIBILITY = re.compile(
    r"\b(eligible|eligibility|can i take|can i apply|am i allowed|may i take)\b",
    re.IGNORECASE,
)
_CALCULATION = re.compile(
    r"\b(deducted|chargeable|how many leave days|how many days will|calculate)\b",
    re.IGNORECASE,
)
_BALANCE = re.compile(
    r"\b(balance|balances|remaining)\b|\bhow many\b.+\b(have|left)\b",
    re.IGNORECASE,
)
_POLICY = re.compile(
    r"\b(policy|policies|work from home|wfh|encash\w*|carry forward|carried forward)\b",
    re.IGNORECASE,
)
_HOLIDAY_FACT = re.compile(
    r"\b(company holidays|planned holidays|holiday list|holidays in)\b"
    r"|\b(what|which|show|list)\b(?:\s+\w+){0,6}\s+holidays?\b"
    r"|\bis\b.+\ba\b.+\bholiday\b",
    re.IGNORECASE,
)
_HOLIDAY_RATIONALE = re.compile(
    r"\b(why|rationale|weekly offs?|mandatory leave)\b",
    re.IGNORECASE,
)
_SALARY = re.compile(
    r"\b(salary|salaries|payroll|compensation|payslip|pay slip|ctc|wages?|bonus|increment)\b",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"^(what about|how about|and what about|same for|what if)\b",
    re.IGNORECASE,
)
_PERSONAL = re.compile(
    r"\b(balance|balances|history|remaining|eligible|eligibility|request|requests|"
    r"used|entitled|record|records|salary|show|my leave)\b",
    re.IGNORECASE,
)
_DAYS = re.compile(r"\b(\d+(?:\.\d+)?)\s+days?\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d{2})\b")
_EMPLOYEE_CODE = re.compile(r"\bEMP\d{3}\b", re.IGNORECASE)
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_DATE_PATTERN = re.compile(
    rf"\b(\d{{4}}-\d{{2}}-\d{{2}})\b|"
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})"
    rf"(?:\s*,?\s*(\d{{4}}))?\b",
    re.IGNORECASE,
)
_LEAVE_PHRASES = (
    ("CL", ("casual leave", "casual")),
    ("SL", ("sick leave", "sick")),
    ("EL", ("earned leave", "earned")),
    ("PL", ("privilege leave", "privilege")),
)


def classify_message(message: str, employee: dict, history: list[dict] | None) -> dict:
    """Return the intent and the slots the tool nodes need."""
    text = " ".join((message or "").split())
    previous = _latest_context(history or [])
    follow_up = bool(_FOLLOW_UP.match(text))

    if not text:
        return _decision("unknown", error="Enter a question.")
    if _SALARY.search(text):
        return _decision("unsupported")
    try:
        mentions_other = _mentions_other_employee(text, employee)
    except LeaveToolError as exc:
        return _decision("unknown", error=str(exc))
    if mentions_other:
        return _decision("privacy")

    explicit = _explicit_intent(text)
    parsed_type = _leave_type(text)
    parsed_days = _requested_days(text)
    date_status, start_date, end_date, date_error = _date_range(text)
    if date_status == "invalid":
        return _decision(explicit or "calculation", error=date_error)

    if explicit is None and parsed_type and not _waiting_for_leave_type(previous):
        # A newer question wins. Do not reuse dates from an older request.
        if previous.get("intent") not in {"eligibility", "calculation", "balance"}:
            pending = _context_waiting_for_leave_type(history or [])
            if pending:
                previous = pending

    # "Casual leave" after "which leave type?" continues that request.
    supplies_type = (
        explicit is None
        and parsed_type is not None
        and _waiting_for_leave_type(previous)
    )
    continues = follow_up or supplies_type

    intent = explicit
    if intent is None and continues:
        intent = previous.get("intent")
    if (
        intent == "calculation"
        and follow_up
        and parsed_days is not None
        and date_status != "found"
    ):
        intent = "eligibility"
    if intent not in {
        "policy",
        "balance",
        "history",
        "calculation",
        "eligibility",
        "holiday",
    }:
        return _decision("unknown")

    if explicit and not follow_up:
        leave_type = parsed_type
    else:
        leave_type = parsed_type or previous.get("leave_type")

    named_month = _calendar_month(text)
    if date_status == "found":
        resolved_start, resolved_end = start_date, end_date
    elif date_status == "single" and intent in {"eligibility", "calculation", "holiday"}:
        resolved_start = resolved_end = start_date
    elif follow_up and parsed_days is not None:
        resolved_start, resolved_end = None, None
    elif continues and named_month is None:
        resolved_start = previous.get("start_date")
        resolved_end = previous.get("end_date")
    else:
        resolved_start, resolved_end = None, None

    if intent == "holiday" and date_status == "single" and start_date:
        month = date.fromisoformat(start_date).month
    elif named_month is not None:
        month = named_month
    elif continues:
        month = previous.get("month")
    else:
        month = None

    if parsed_days is not None:
        requested_days = parsed_days
    elif continues and date_status != "found":
        requested_days = previous.get("requested_days")
    else:
        requested_days = None

    year = _year(text)
    if year is None and continues:
        year = previous.get("year")

    return _decision(
        intent,
        leave_type=leave_type,
        start_date=resolved_start,
        end_date=resolved_end,
        requested_days=requested_days,
        year=year,
        month=month,
    )


def _decision(intent: str, error: str | None = None, **slots: object) -> dict:
    return {
        "intent": intent,
        "leave_type": slots.get("leave_type"),
        "start_date": slots.get("start_date"),
        "end_date": slots.get("end_date"),
        "requested_days": slots.get("requested_days"),
        "year": slots.get("year"),
        "month": slots.get("month"),
        "error": error,
    }


def _waiting_for_leave_type(context: dict) -> bool:
    return (
        context.get("intent") in {"eligibility", "calculation", "balance"}
        and not context.get("leave_type")
        and bool(context.get("start_date"))
    )


def _context_waiting_for_leave_type(history: list[dict]) -> dict | None:
    """Find an earlier turn that asked which leave type to use."""
    for item in reversed(history):
        context = item.get("context") if isinstance(item, dict) else None
        if item.get("role") == "assistant" and isinstance(context, dict):
            if _waiting_for_leave_type(context):
                return context
    return None


def _latest_context(history: list[dict]) -> dict:
    for item in reversed(history):
        context = item.get("context") if isinstance(item, dict) else None
        if item.get("role") == "assistant" and isinstance(context, dict):
            return context
    return {}


def _explicit_intent(text: str) -> str | None:
    if _HISTORY.search(text):
        return "history"
    if _ELIGIBILITY.search(text):
        return "eligibility"
    if _CALCULATION.search(text):
        return "calculation"
    if _BALANCE.search(text):
        return "balance"
    if _is_holiday_calendar(text):
        return "holiday"
    if _POLICY.search(text):
        return "policy"
    if re.search(r"\bwhat is\b", text, re.IGNORECASE) and _leave_type(text):
        if not re.search(r"\b(my|i)\b", text, re.IGNORECASE):
            return "policy"
    return None


def _leave_type(text: str) -> str | None:
    lowered = text.lower()
    for code, phrases in _LEAVE_PHRASES:
        if any(phrase in lowered for phrase in phrases):
            return code
    for code in ("CL", "SL", "EL", "PL"):
        if re.search(rf"\b{code}\b", text, re.IGNORECASE):
            return code
    return None


def _requested_days(text: str) -> int | float | None:
    match = _DAYS.search(text)
    if match is None:
        return None
    value = float(match.group(1))
    if value.is_integer():
        return int(value)
    return value


def _year(text: str) -> int | None:
    found = _YEAR.findall(text)
    if not found:
        return None
    return int(found[-1])


def _date_range(text: str) -> tuple[str, str | None, str | None, str | None]:
    """Return status, start, end, and an error message."""
    parsed: list[tuple[int, int, int | None]] = []
    for match in _DATE_PATTERN.finditer(text):
        iso, day_text, month_text, year_text = match.groups()
        if iso:
            year_text, month_text, day_text = iso.split("-")
            try:
                parsed_date = date(int(year_text), int(month_text), int(day_text))
            except ValueError:
                return ("invalid", None, None, f"Invalid date '{iso}'. Use a real calendar date.")
            if parsed_date.isoformat() != iso:
                return ("invalid", None, None, f"Invalid date '{iso}'. Use a real calendar date.")
            parsed.append((parsed_date.year, parsed_date.month, parsed_date.day))
            continue
        month = _MONTHS[month_text.lower()]
        year = int(year_text) if year_text else None
        day = int(day_text)
        if day < 1 or day > 31:
            return ("invalid", None, None, f"Invalid date '{match.group(0)}'.")
        parsed.append((year, month, day))

    if len(parsed) == 1:
        single_year, single_month, single_day = parsed[0]
        if single_year is None:
            single_year = DEFAULT_LEAVE_YEAR
        try:
            single = date(single_year, single_month, single_day)
        except ValueError:
            return ("invalid", None, None, "That date is not a real calendar date.")
        return ("single", single.isoformat(), None, None)

    if len(parsed) < 2:
        return ("none", None, None, None)

    start_year, start_month, start_day = parsed[0]
    end_year, end_month, end_day = parsed[1]
    if start_year is None:
        start_year = end_year if end_year is not None else DEFAULT_LEAVE_YEAR
    if end_year is None:
        end_year = start_year
    try:
        start = date(start_year, start_month, start_day)
        end = date(end_year, end_month, end_day)
    except ValueError:
        return ("invalid", None, None, "One of those dates is not a real calendar date.")
    return ("found", start.isoformat(), end.isoformat(), None)


def _is_holiday_calendar(text: str) -> bool:
    """True for a factual holiday-list question, not a policy rationale question."""
    if not _HOLIDAY_FACT.search(text):
        return False
    if _HOLIDAY_RATIONALE.search(text):
        return False
    if _POLICY.search(text) and not re.search(
        r"\b(company holidays|planned holidays|holidays in|is\b.+\bholiday)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    return True


def _calendar_month(text: str) -> int | None:
    """Return a month named on its own, such as 'in October', not '26 January'."""
    dated_months = {
        match.group(1).lower()
        for match in re.finditer(
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})\b",
            text,
            re.IGNORECASE,
        )
    }
    for match in re.finditer(rf"\b({_MONTH_PATTERN})\b", text, re.IGNORECASE):
        name = match.group(1).lower()
        if name not in dated_months:
            return _MONTHS[name]
    return None


def policy_search_query(message: str, leave_type: str | None) -> str:
    """Turn a short follow-up into a policy search when the topic is known."""
    text = " ".join((message or "").split())
    topic = {
        "CL": "casual leave",
        "SL": "sick leave",
        "EL": "earned leave",
        "PL": "privilege leave",
    }.get(leave_type or "")
    if topic and _FOLLOW_UP.match(text):
        return f"What is the {topic} policy?"
    return text


def _mentions_other_employee(text: str, employee: dict) -> bool:
    """True when the message asks for another employee's private HR data."""
    if not _PERSONAL.search(text) and not _EMPLOYEE_CODE.search(text):
        return False
    if _policy_only(text):
        return False

    current_id = employee.get("id")
    current_code = str(employee.get("employee_code") or "").lower()
    for code in _EMPLOYEE_CODE.findall(text):
        if code.lower() != current_code:
            return True

    for person in _employee_directory():
        if person["id"] == current_id:
            continue
        if _name_mentioned(text, person["name"]):
            return True
    return False


def _policy_only(text: str) -> bool:
    return bool(_POLICY.search(text)) and not bool(_PERSONAL.search(text))


def _name_mentioned(text: str, value: str) -> bool:
    lowered = text.lower()
    candidate = value.lower().strip()
    if not candidate:
        return False
    if candidate in lowered:
        return True
    for part in candidate.replace("@", " ").split():
        if len(part) >= 4 and re.search(rf"\b{re.escape(part)}\b", lowered):
            return True
    return False


def _employee_directory() -> list[dict]:
    try:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, employee_code, name FROM employees"
            ).fetchall()
    except sqlite3.Error as exc:
        raise LeaveToolError("The employee directory could not be read.") from exc
    return [
        {
            "id": row["id"],
            "employee_code": row["employee_code"],
            "name": row["name"],
        }
        for row in rows
    ]
