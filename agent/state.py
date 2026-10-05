"""Conversation state for the HR Chat Agent graph.

The authenticated employee is placed here by the Streamlit session.
Graph nodes read that identity. They do not take an employee id from the
user message.
"""

from __future__ import annotations

from typing import TypedDict


class HRAgentState(TypedDict, total=False):
    """One turn through the LangGraph workflow."""

    message: str
    history: list[dict]
    employee: dict
    intent: str
    leave_type: str | None
    start_date: str | None
    end_date: str | None
    requested_days: int | float | None
    year: int | None
    month: int | None
    tool_trace: list[dict]
    balance: dict | None
    history_result: dict | None
    calculation: dict | None
    eligibility: dict | None
    holiday_result: dict | None
    policy: dict | None
    error: str | None
    reply: str
    context: dict
