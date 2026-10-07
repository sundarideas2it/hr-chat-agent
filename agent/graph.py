"""LangGraph workflow for the HR Chat Agent.

START
  -> select_intent   (deterministic router; no Gemini call)
       -> leave_balance
       -> leave_history
       -> holiday_lookup
       -> leave_calculation
            -> eligibility, when the question asks whether leave can be taken
       -> eligibility
       -> respond, for another employee's private data or an unsupported topic
       -> policy_retrieval   (the only node that calls Gemini)
  -> respond
  -> END

Tool nodes call the existing Python functions. employee_id always comes from
the employee dict supplied by the application. A policy question that cannot
reach Gemini returns a short unavailable message and does not invent an answer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from agent.intent import classify_message, policy_search_query
from agent.prompts import (
    APPROVAL_REPLY_NOTE,
    CROSS_EMPLOYEE_REFUSAL,
    TOOL_ELIGIBILITY,
    TOOL_HOLIDAY_LOOKUP,
    TOOL_LEAVE_BALANCE,
    TOOL_LEAVE_CALCULATOR,
    TOOL_LEAVE_HISTORY,
    POLICY_QUOTA_UNAVAILABLE,
    TOOL_POLICY_SEARCH,
    UNKNOWN_REQUEST_REPLY,
    UNSUPPORTED_SALARY_REPLY,
)
from agent.state import HRAgentState
from rag.answer import answer_policy_question
from rag.config import NOT_FOUND_MESSAGE
from rag.errors import public_error_message
from tools.eligibility import check_leave_eligibility
from tools.errors import LeaveToolError
from tools.holidays import get_holidays
from tools.leave_balance import get_leave_balance, get_leave_history
from tools.leave_calculator import calculate_leave_days
from tools.policy_rules import DEFAULT_LEAVE_YEAR
from tools.policy_search import search_hr_policy

# Stop the page from staying on Running while the Gemini client sleeps
# through quota retries. This is a wall-clock limit around search and answer.
_POLICY_WAIT_SECONDS = 20

_LEAVE_NAMES = {
    "CL": "Casual Leave",
    "SL": "Sick Leave",
    "EL": "Earned Leave",
    "PL": "Privilege Leave",
}


def select_intent(state: HRAgentState) -> dict:
    """Decide which tool path this message needs."""
    try:
        decision = classify_message(
            state.get("message") or "",
            state.get("employee") or {},
            state.get("history") or [],
        )
    except LeaveToolError as exc:
        return {"intent": "unknown", "error": str(exc), "reply": str(exc), "tool_trace": []}

    update = {
        "intent": decision["intent"],
        "leave_type": decision["leave_type"],
        "start_date": decision["start_date"],
        "end_date": decision["end_date"],
        "requested_days": decision["requested_days"],
        "year": decision["year"],
        "month": decision["month"],
        "error": decision["error"],
        "tool_trace": [],
        "reply": "",
    }
    if decision["error"]:
        update["reply"] = decision["error"]
    elif decision["intent"] == "privacy":
        update["reply"] = CROSS_EMPLOYEE_REFUSAL
    elif decision["intent"] == "unsupported":
        update["reply"] = UNSUPPORTED_SALARY_REPLY
    elif decision["intent"] == "unknown":
        update["reply"] = UNKNOWN_REQUEST_REPLY
    return update


def route_after_intent(state: HRAgentState) -> str:
    if state.get("reply") or state.get("error"):
        return "respond"
    intent = state.get("intent")
    if intent == "policy":
        return "policy_retrieval"
    if intent == "balance":
        return "leave_balance"
    if intent == "history":
        return "leave_history"
    if intent == "calculation":
        return "leave_calculation"
    if intent == "holiday":
        return "holiday_lookup"
    if intent == "eligibility":
        if state.get("start_date") and state.get("end_date"):
            return "leave_calculation"
        return "eligibility"
    return "respond"


def policy_retrieval(state: HRAgentState) -> dict:
    """Retrieve policy passages and ask Gemini to answer from those passages."""
    question = policy_search_query(state.get("message") or "", state.get("leave_type"))
    trace = _trace(state, TOOL_POLICY_SEARCH)
    try:
        result = _policy_answer(question)
    except Exception as exc:
        message = _policy_failure_reply(exc)
        return {"tool_trace": trace, "error": message, "reply": message}
    return {"tool_trace": trace, "policy": result}


def _policy_answer(question: str) -> dict:
    """Search and answer, but do not block the chat longer than the deadline."""
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="policy")
    future = executor.submit(_search_and_answer, question)
    try:
        return future.result(timeout=_POLICY_WAIT_SECONDS)
    except TimeoutError:
        if future.done():
            raise
        raise TimeoutError(
            "The policy assistant timed out before Gemini responded."
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _search_and_answer(question: str) -> dict:
    matches = search_hr_policy(question)
    return answer_policy_question(question, matches=matches)


def _policy_failure_reply(exc: Exception) -> str:
    """Hide provider errors. Quota failures keep the database tools available."""
    public = public_error_message(exc)
    combined = f"{exc} {public}".lower()
    if "resource_exhausted" in combined or "quota" in combined:
        return POLICY_QUOTA_UNAVAILABLE
    return public


def leave_balance_node(state: HRAgentState) -> dict:
    trace = _trace(state, TOOL_LEAVE_BALANCE)
    try:
        result = get_leave_balance(
            _employee_id(state.get("employee") or {}),
            state.get("leave_type"),
            state.get("year"),
        )
    except LeaveToolError as exc:
        return {"tool_trace": trace, "error": str(exc), "reply": str(exc)}
    return {"tool_trace": trace, "balance": result}


def leave_history_node(state: HRAgentState) -> dict:
    trace = _trace(state, TOOL_LEAVE_HISTORY)
    try:
        result = get_leave_history(
            _employee_id(state.get("employee") or {}),
            state.get("year"),
        )
    except LeaveToolError as exc:
        return {"tool_trace": trace, "error": str(exc), "reply": str(exc)}
    return {"tool_trace": trace, "history_result": result}


def leave_calculation_node(state: HRAgentState) -> dict:
    if not state.get("start_date") or not state.get("end_date"):
        message = "Tell me the start and end dates to calculate leave days."
        return {"error": message, "reply": message}
    trace = _trace(state, TOOL_LEAVE_CALCULATOR)
    try:
        result = calculate_leave_days(state["start_date"], state["end_date"])
    except LeaveToolError as exc:
        return {"tool_trace": trace, "error": str(exc), "reply": str(exc)}
    return {"tool_trace": trace, "calculation": result}


def holiday_lookup_node(state: HRAgentState) -> dict:
    """Read company holidays from SQLite. This does not call Gemini."""
    trace = _trace(state, TOOL_HOLIDAY_LOOKUP)
    try:
        result = get_holidays(year=state.get("year"), month=state.get("month"))
    except LeaveToolError as exc:
        return {"tool_trace": trace, "error": str(exc), "reply": str(exc)}
    query_date = state.get("start_date")
    if query_date and query_date == state.get("end_date"):
        result = {**result, "query_date": query_date}
    return {"tool_trace": trace, "holiday_result": result}


def route_after_calculation(state: HRAgentState) -> str:
    if state.get("reply") or state.get("error"):
        return "respond"
    if state.get("intent") == "eligibility":
        return "eligibility"
    return "respond"


def eligibility_node(state: HRAgentState) -> dict:
    leave_type = state.get("leave_type")
    if not leave_type:
        message = "Tell me which leave type you mean, such as Casual Leave or Sick Leave."
        return {"error": message, "reply": message}
    requested = state.get("requested_days")
    calculation = state.get("calculation")
    if calculation is not None:
        requested = calculation["chargeable_leave_days"]
    if requested is None:
        message = "Tell me the dates or how many days you want to take."
        return {"error": message, "reply": message}

    trace = _trace(state, TOOL_LEAVE_BALANCE)
    trace = trace + [{"name": TOOL_ELIGIBILITY}]
    try:
        result = check_leave_eligibility(
            _employee_id(state.get("employee") or {}),
            leave_type,
            requested,
            year=state.get("year"),
        )
    except LeaveToolError as exc:
        return {"tool_trace": trace, "error": str(exc), "reply": str(exc)}
    return {"tool_trace": trace, "eligibility": result, "requested_days": requested}


def respond(state: HRAgentState) -> dict:
    """Turn tool results into an employee-facing reply. This does not call Gemini."""
    if state.get("reply"):
        reply = state["reply"]
    elif state.get("error"):
        reply = state["error"]
    elif state.get("intent") == "balance" and state.get("balance"):
        reply = _format_balance(state["balance"])
    elif state.get("intent") == "history" and state.get("history_result"):
        reply = _format_history(state["history_result"])
    elif state.get("intent") == "calculation" and state.get("calculation"):
        reply = _format_calculation(state["calculation"])
    elif state.get("intent") == "eligibility" and state.get("eligibility"):
        reply = _format_eligibility(state)
    elif state.get("intent") == "holiday" and state.get("holiday_result"):
        reply = _format_holidays(state["holiday_result"])
    elif state.get("intent") == "policy":
        reply = _format_policy(state.get("policy") or {})
    else:
        reply = state.get("error") or UNKNOWN_REQUEST_REPLY
    return {"reply": reply, "context": _saved_context(state)}


def build_graph():
    """Compile the HR agent graph."""
    graph = StateGraph(HRAgentState)
    graph.add_node("select_intent", select_intent)
    graph.add_node("policy_retrieval", policy_retrieval)
    graph.add_node("leave_balance", leave_balance_node)
    graph.add_node("leave_history", leave_history_node)
    graph.add_node("leave_calculation", leave_calculation_node)
    graph.add_node("eligibility", eligibility_node)
    graph.add_node("holiday_lookup", holiday_lookup_node)
    graph.add_node("respond", respond)
    graph.add_edge(START, "select_intent")
    graph.add_conditional_edges(
        "select_intent",
        route_after_intent,
        {
            "policy_retrieval": "policy_retrieval",
            "leave_balance": "leave_balance",
            "leave_history": "leave_history",
            "leave_calculation": "leave_calculation",
            "holiday_lookup": "holiday_lookup",
            "eligibility": "eligibility",
            "respond": "respond",
        },
    )
    graph.add_conditional_edges(
        "leave_calculation",
        route_after_calculation,
        {"eligibility": "eligibility", "respond": "respond"},
    )
    graph.add_edge("policy_retrieval", "respond")
    graph.add_edge("leave_balance", "respond")
    graph.add_edge("leave_history", "respond")
    graph.add_edge("holiday_lookup", "respond")
    graph.add_edge("eligibility", "respond")
    graph.add_edge("respond", END)
    return graph.compile()


@lru_cache(maxsize=1)
def get_graph():
    return build_graph()


def run_agent(
    message: str,
    employee: dict,
    history: list[dict] | None = None,
) -> dict:
    """Answer one message for the signed-in employee.

    ``employee`` must be the authenticated session record. The message is
    never trusted as a source of employee_id.
    """
    try:
        employee_id = _employee_id(employee)
    except LeaveToolError as exc:
        return {"reply": str(exc), "tools_used": [], "context": {}}

    result = get_graph().invoke(
        {
            "message": message,
            "history": [dict(item) for item in (history or [])],
            "employee": {
                "id": employee_id,
                "employee_code": employee.get("employee_code"),
                "name": employee.get("name"),
                "department": employee.get("department"),
            },
        }
    )
    tools_used: list[str] = []
    for item in result.get("tool_trace") or []:
        name = item.get("name")
        if name and name not in tools_used:
            tools_used.append(name)
    return {
        "reply": result.get("reply") or UNKNOWN_REQUEST_REPLY,
        "tools_used": tools_used,
        "context": result.get("context") or {},
    }


def _employee_id(employee: dict) -> int:
    if not isinstance(employee, dict):
        raise LeaveToolError("The signed-in employee is missing. Sign in again and retry.")
    employee_id = employee.get("id")
    if isinstance(employee_id, bool) or not isinstance(employee_id, int):
        raise LeaveToolError("The signed-in employee is missing. Sign in again and retry.")
    return employee_id


def _trace(state: HRAgentState, name: str) -> list[dict]:
    trace = list(state.get("tool_trace") or [])
    trace.append({"name": name})
    return trace


def _saved_context(state: HRAgentState) -> dict:
    requested = state.get("requested_days")
    eligibility = state.get("eligibility") or {}
    if eligibility.get("requested_days") is not None:
        requested = eligibility["requested_days"]
    return {
        "intent": state.get("intent"),
        "leave_type": state.get("leave_type"),
        "start_date": state.get("start_date"),
        "end_date": state.get("end_date"),
        "requested_days": requested,
        "year": state.get("year") or DEFAULT_LEAVE_YEAR,
        "month": state.get("month"),
    }


def _format_balance(result: dict) -> str:
    balances = result.get("balances") or []
    year = result.get("year")
    if not balances:
        return f"No leave balances are recorded for {year}."
    if len(balances) == 1:
        item = balances[0]
        lines = [
            (
                f"You have {_days(item['remaining'])} of {item['leave_name']} "
                f"remaining for {year}."
            ),
            f"Entitled: {_days(item['entitled'])}",
            f"Used: {_days(item['used'])}",
            f"Remaining: {_days(item['remaining'])}",
        ]
        return "\n".join(lines)

    lines = [f"Your leave balances for {year}:"]
    for item in balances:
        lines.append(
            f"- {item['leave_name']} ({item['leave_type']}): "
            f"entitled {item['entitled']}, used {item['used']}, "
            f"remaining {item['remaining']}"
        )
    return "\n".join(lines)


def _format_history(result: dict) -> str:
    requests = result.get("requests") or []
    year = result.get("year")
    if not requests:
        return f"You have no leave requests recorded for {year}."
    lines = [f"Your leave requests for {year}:"]
    for item in requests:
        lines.append(
            f"- {item['leave_name']}: {_pretty(item['start_date'])} to "
            f"{_pretty(item['end_date'])}, {_days(item['days'])}, {item['status']}"
        )
    return "\n".join(lines)


def _format_calculation(calculation: dict) -> str:
    calendar = calculation["calendar_days"]
    chargeable = calculation["chargeable_leave_days"]
    lines = [
        (
            f"{_span_label(calculation['start_date'], calculation['end_date'])} "
            f"spans {_days(calendar, 'calendar')}."
        )
    ]
    excluded = calculation.get("excluded_dates") or []
    holidays = [item for item in excluded if item.get("reason") == "public holiday"]
    weekly_offs = [item for item in excluded if item.get("reason") == "weekly off"]
    if len(holidays) == 1:
        lines.append(f"{holidays[0]['name']} is excluded as a public holiday.")
    elif holidays:
        names = " and ".join(item["name"] for item in holidays)
        lines.append(f"{names} are excluded as public holidays.")
    else:
        lines.append("No company holiday falls in this range.")
    off_line = _weekly_off_line(weekly_offs)
    if off_line:
        lines.append(off_line)
    lines.append(f"Chargeable leave: {_days(chargeable)}.")
    return "\n".join(lines)


def _format_eligibility(state: HRAgentState) -> str:
    result = state["eligibility"]
    leave_name = _LEAVE_NAMES.get(state.get("leave_type") or "", "leave")
    requested = result["requested_days"]
    remaining = result["remaining_balance"]
    lines: list[str] = []
    calculation = state.get("calculation")
    if calculation:
        lines.append(_format_calculation(calculation))
        lines.append("")
    if calculation and calculation.get("chargeable_leave_days") == 0:
        lines.append(
            f"No {leave_name} is charged. Every day in this range is a "
            "weekly off or a public holiday."
        )
        return "\n".join(lines)
    if result.get("eligible"):
        lines.append(
            f"You have {_days(remaining)} of {leave_name} remaining and this "
            f"request requires {_days(requested, 'chargeable')}, so you are "
            "eligible based on the available balance."
        )
    elif remaining is None:
        detail = "This leave type is not available on your account."
        if result.get("checks"):
            detail = result["checks"][0]["detail"]
        lines.append(detail)
        lines.append("You are not eligible for this request.")
    else:
        lines.append(
            f"You have {_days(remaining)} of {leave_name} remaining, but this "
            f"request needs {_days(requested)}, so you are not eligible because "
            "the available balance is insufficient."
        )
    lines.append(APPROVAL_REPLY_NOTE)
    return "\n".join(lines)


def _format_holidays(result: dict) -> str:
    source = result.get("source") or "Holiday List - 2026.pdf"
    holidays = result.get("holidays") or []
    query_date = result.get("query_date")
    if query_date:
        match = next((item for item in holidays if item["date"] == query_date), None)
        if match:
            body = f"Yes. {_pretty(query_date)} is {match['name']}, a company holiday."
        else:
            body = f"No. {_pretty(query_date)} is not on the company holiday list."
        return f"{body}\nSource: {source}"

    year = result.get("year")
    month = result.get("month")
    if month:
        period = f"{date(int(year), int(month), 1).strftime('%B')} {year}"
    else:
        period = str(year)
    if not holidays:
        return f"No company holidays are listed for {period}.\nSource: {source}"
    lines = [f"Company holidays in {period}:"]
    for item in holidays:
        lines.append(f"- {_pretty(item['date'])}: {item['name']}")
    lines.append(f"Source: {source}")
    return "\n".join(lines)


def _format_policy(policy: dict) -> str:
    answer = (policy.get("answer") or "").strip() or NOT_FOUND_MESSAGE
    lines = [answer]
    sources = policy.get("sources") or []
    if sources:
        lines.append("")
        lines.append("Source:")
        lines.extend(f"- {source}" for source in sources)
    return "\n".join(lines)


def _weekly_off_line(weekly_offs: list[dict]) -> str:
    names: list[str] = []
    for item in weekly_offs:
        name = item.get("name") or "Weekly off"
        if name not in names:
            names.append(name)
    if not names:
        return ""
    if len(names) == 1:
        return f"{names[0]} is excluded as a weekly off."
    return f"{' and '.join(names)} are excluded as weekly offs."


def _span_label(start_iso: str, end_iso: str) -> str:
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    if start == end:
        return f"{start.day} {start.strftime('%B %Y')}"
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {start.strftime('%B %Y')}"
    if start.year == end.year:
        return (
            f"{start.day} {start.strftime('%B')}–"
            f"{end.day} {end.strftime('%B %Y')}"
        )
    return (
        f"{start.day} {start.strftime('%B %Y')}–"
        f"{end.day} {end.strftime('%B %Y')}"
    )


def _pretty(iso_date: str) -> str:
    value = date.fromisoformat(iso_date)
    return f"{value.day} {value.strftime('%B %Y')}"


def _days(value: object, adjective: str = "") -> str:
    number = int(value) if float(value).is_integer() else value
    unit = "day" if number == 1 else "days"
    if adjective:
        return f"{number} {adjective} {unit}"
    return f"{number} {unit}"
