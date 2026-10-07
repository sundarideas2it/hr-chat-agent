"""Wording owned by the HR Chat Agent.

Gemini is used only to phrase an answer from retrieved policy passages.
Leave balances, day counts, and eligibility are written from tool results
by the graph, using the sentences below. The signed-in employee comes from
the application session and is never a model-chosen tool argument.
"""

from __future__ import annotations

CROSS_EMPLOYEE_REFUSAL = (
    "I can only access HR information associated with your authenticated "
    "employee account."
)

UNSUPPORTED_SALARY_REPLY = (
    "Salary and payroll information is not available through the HR Chat Agent. "
    "I can help with your leave balance, leave history, leave-day calculations, "
    "leave eligibility, and HR policy questions."
)

POLICY_QUOTA_UNAVAILABLE = (
    "The policy knowledge service is temporarily unavailable because the "
    "configured LLM quota has been reached. Database and leave-management "
    "tools are still available."
)

UNKNOWN_REQUEST_REPLY = (
    "I can help with your leave balance, leave history, leave-day calculations, "
    "leave eligibility, and HR policy questions."
)

APPROVAL_REPLY_NOTE = (
    "Manager approval is still required. Eligibility does not mean the leave "
    "is approved."
)

TOOL_POLICY_SEARCH = "Policy Search"
TOOL_LEAVE_BALANCE = "Leave Balance"
TOOL_LEAVE_HISTORY = "Leave History"
TOOL_LEAVE_CALCULATOR = "Leave Calculator"
TOOL_ELIGIBILITY = "Eligibility Checker"
TOOL_HOLIDAY_LOOKUP = "Holiday Lookup"
