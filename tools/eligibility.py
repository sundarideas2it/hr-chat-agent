"""Deterministic leave eligibility for the signed-in employee.

Balance arithmetic uses SQLite. Extra constraints are the rules read from
Revised Leave Policy - I2I.pdf. A passing result is not manager approval.
"""

from __future__ import annotations

from tools.errors import LeaveToolError
from tools.leave_balance import get_leave_balance
from tools.policy_rules import APPROVAL_WARNING, DEFAULT_LEAVE_YEAR, constraints_for


def check_leave_eligibility(
    employee_id: int,
    leave_type_code: str,
    requested_days: int | float,
    policy_rules: list | None = None,
    year: int | None = None,
) -> dict:
    """Check whether a request fits the recorded balance and known policy rules."""
    if isinstance(requested_days, bool) or not isinstance(requested_days, (int, float)):
        raise LeaveToolError("Requested days must be a number.")

    leave_year = year if year is not None else DEFAULT_LEAVE_YEAR
    requested = float(requested_days)
    checks: list[dict] = []
    warnings = [APPROVAL_WARNING]

    try:
        balance = get_leave_balance(employee_id, leave_type_code, leave_year)
    except LeaveToolError as exc:
        message = str(exc)
        missing_record = message.startswith("Unknown leave type") or (
            "balance is recorded" in message
        )
        if missing_record:
            return _failed(
                requested_days=requested,
                checks=[
                    {
                        "name": "leave_type",
                        "passed": False,
                        "detail": message,
                    }
                ],
                warnings=warnings
                + ["The balance check was not run because the leave record is missing."],
            )
        raise

    record = balance["balances"][0]
    checks.append(
        {
            "name": "leave_type",
            "passed": True,
            "detail": f"{record['leave_name']} ({record['leave_type']}) is recorded for this employee.",
        }
    )
    positive = requested > 0
    checks.append(
        {
            "name": "requested_days",
            "passed": positive,
            "detail": (
                f"Requested { _display(requested) } day(s)."
                if positive
                else "Requested days must be greater than zero."
            ),
        }
    )
    remaining = float(record["remaining"])
    enough = positive and requested <= remaining
    checks.append(
        {
            "name": "balance",
            "passed": enough,
            "detail": (
                f"Remaining balance is { _display(remaining) } day(s)."
                if enough
                else (
                    f"Requested { _display(requested) } day(s), but only "
                    f"{ _display(remaining) } day(s) remain."
                )
            ),
        }
    )

    constraints = constraints_for(record["leave_type"])
    constraints.extend(_caller_rules(policy_rules))
    if not any(item["rule"] for item in constraints):
        warnings.append(
            "No additional policy constraint was available beyond the balance check."
        )

    return {
        "eligible": all(check["passed"] for check in checks),
        "requested_days": _display(requested),
        "remaining_balance": _display(remaining),
        "checks": checks,
        "policy_constraints": constraints,
        "warnings": warnings,
    }


def _caller_rules(policy_rules: list | None) -> list[dict]:
    if not policy_rules:
        return []
    extra = []
    for rule in policy_rules:
        if isinstance(rule, str) and rule.strip():
            extra.append({"rule": rule.strip(), "source": "caller-supplied rule"})
        elif isinstance(rule, dict) and str(rule.get("rule", "")).strip():
            extra.append(
                {
                    "rule": str(rule["rule"]).strip(),
                    "source": str(rule.get("source") or "caller-supplied rule"),
                }
            )
    return extra


def _failed(requested_days: float, checks: list[dict], warnings: list[str]) -> dict:
    return {
        "eligible": False,
        "requested_days": _display(requested_days),
        "remaining_balance": None,
        "checks": checks,
        "policy_constraints": [],
        "warnings": warnings,
    }


def _display(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return float(value)
