"""Streamlit entry point for the HR Chat Agent.

Employees sign in with an employee code and password. The signed-in
employee record is stored in session state. A temporary policy question
box answers from retrieved HR documents. Chat is not implemented yet.
"""

from __future__ import annotations

import os
from datetime import date

import streamlit as st

from database.db import authenticate, init_db
from database.seed import DEMO_PASSWORD, seed

_DEMO_EMPLOYEE_CODE = "EMP001"


def _ensure_database() -> None:
    init_db()
    seed()


def _render_login() -> None:
    with st.form("login_form"):
        employee_code = st.text_input("Employee ID")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        employee = authenticate(employee_code, password)
        if employee is None:
            st.error("Invalid employee ID or password.")
        else:
            st.session_state["employee"] = employee
            st.rerun()

    st.subheader("Demo Credentials")
    st.write(f"Employee ID: {_DEMO_EMPLOYEE_CODE}")
    st.write(f"Password: {DEMO_PASSWORD}")


def _render_home(employee: dict) -> None:
    st.write(f"Welcome, {employee['name']}")
    st.write(f"Employee ID: {employee['employee_code']}")
    st.write(f"Department: {employee['department']}")
    if st.button("Logout"):
        st.session_state["employee"] = None
        st.rerun()
    st.write("HR Assistant chat will appear here.")
    _render_policy_assistant()
    _render_leave_tools(employee)


def _render_policy_assistant() -> None:
    st.subheader("HR Policy Assistant")
    st.caption(
        "Answers use only the HR policy documents in the policies folder."
    )
    with st.form("policy_question_form"):
        question = st.text_input("Ask an HR policy question")
        asked = st.form_submit_button("Ask HR")

    if not asked:
        return
    if not question.strip():
        st.error("Enter a policy question.")
        return

    try:
        from rag.answer import answer_policy_question

        result = answer_policy_question(question)
    except Exception as exc:
        st.error(_public_error_message(exc))
        return

    st.write(result["answer"])
    if result["sources"]:
        st.write("Source:")
        for citation in result["sources"]:
            st.write(citation)


def _render_leave_tools(employee: dict) -> None:
    """Demo the deterministic leave tools for the signed-in employee only."""
    from tools.eligibility import check_leave_eligibility
    from tools.errors import LeaveToolError
    from tools.leave_balance import get_leave_balance, get_leave_history, list_leave_types
    from tools.leave_calculator import calculate_leave_days
    from tools.policy_rules import LEAVE_TYPE_NOTES

    st.subheader("Leave Tools Demo")
    st.caption(
        "Balances and calculations use the signed-in employee only. "
        "There is no field for another employee id."
    )
    employee_id = int(employee["id"])

    if st.button("My Leave Balances"):
        try:
            st.session_state["leave_balance_result"] = get_leave_balance(employee_id)
        except LeaveToolError as exc:
            st.session_state["leave_balance_result"] = None
            st.error(str(exc))
    balance_result = st.session_state.get("leave_balance_result")
    if balance_result:
        st.write(f"Employee ID: {balance_result['employee_code']}")
        st.write(f"Year: {balance_result['year']}")
        for item in balance_result["balances"]:
            st.write(
                f"{item['leave_type']} ({item['leave_name']}): "
                f"entitled {item['entitled']}, used {item['used']}, "
                f"remaining {item['remaining']}"
            )
            if item.get("note"):
                st.caption(item["note"])

    if st.button("My Leave History"):
        try:
            st.session_state["leave_history_result"] = get_leave_history(employee_id)
        except LeaveToolError as exc:
            st.session_state["leave_history_result"] = None
            st.error(str(exc))
    history_result = st.session_state.get("leave_history_result")
    if history_result:
        st.write(f"Employee ID: {history_result['employee_code']}")
        if not history_result["requests"]:
            st.write("No leave requests are recorded for this year.")
        for item in history_result["requests"]:
            st.write(
                f"{item['leave_type']} ({item['leave_name']}): "
                f"{item['start_date']} to {item['end_date']}, "
                f"{item['days']} day(s), {item['status']}"
            )

    try:
        leave_types = list_leave_types()
    except LeaveToolError as exc:
        st.error(str(exc))
        return

    labels = [f"{item['code']} — {item['name']}" for item in leave_types]
    selected_label = st.selectbox("Leave Type", labels)
    selected_code = selected_label.split(" — ", 1)[0]
    note = LEAVE_TYPE_NOTES.get(selected_code)
    if note:
        st.caption(note)
    start_date = st.date_input("Start Date", value=date(2026, 1, 24))
    end_date = st.date_input("End Date", value=date(2026, 1, 27))

    if st.button("Calculate Leave"):
        try:
            st.session_state["leave_calculation_result"] = calculate_leave_days(
                start_date.isoformat(),
                end_date.isoformat(),
            )
            st.session_state["leave_calculation_error"] = None
        except LeaveToolError as exc:
            st.session_state["leave_calculation_result"] = None
            st.session_state["leave_calculation_error"] = str(exc)
    if st.session_state.get("leave_calculation_error"):
        st.error(st.session_state["leave_calculation_error"])
    calculation = st.session_state.get("leave_calculation_result")
    if calculation:
        st.write(f"Leave type: {selected_code}")
        st.json(calculation)

    if st.button("Check Eligibility"):
        try:
            counted = calculate_leave_days(start_date.isoformat(), end_date.isoformat())
            eligibility = check_leave_eligibility(
                employee_id,
                selected_code,
                counted["chargeable_leave_days"],
            )
            st.session_state["leave_eligibility_result"] = eligibility
            st.session_state["leave_eligibility_count"] = counted
            st.session_state["leave_eligibility_error"] = None
        except LeaveToolError as exc:
            st.session_state["leave_eligibility_result"] = None
            st.session_state["leave_eligibility_error"] = str(exc)
    if st.session_state.get("leave_eligibility_error"):
        st.error(st.session_state["leave_eligibility_error"])
    eligibility = st.session_state.get("leave_eligibility_result")
    if eligibility:
        st.write(f"Requested leave days: {eligibility['requested_days']}")
        st.write(f"Current remaining balance: {eligibility['remaining_balance']}")
        st.write("Eligible" if eligibility["eligible"] else "Not eligible")
        for constraint in eligibility["policy_constraints"]:
            st.write(f"{constraint['rule']} ({constraint['source']})")
        for warning in eligibility["warnings"]:
            st.warning(warning)
        counted = st.session_state.get("leave_eligibility_count") or {}
        for warning in counted.get("warnings", []):
            st.warning(warning)


def _public_error_message(exc: Exception) -> str:
    message = str(exc).strip() or "The policy assistant could not complete the request."
    secret = os.environ.get("GOOGLE_API_KEY")
    if secret and secret in message:
        message = message.replace(secret, "[REDACTED]")
    return message


def main() -> None:
    st.set_page_config(
        page_title="HR Chat Agent",
        page_icon=":speech_balloon:",
    )
    _ensure_database()

    st.title("HR Chat Agent")
    st.header("AI-powered Employee HR Assistant")

    if "employee" not in st.session_state:
        st.session_state["employee"] = None

    employee = st.session_state["employee"]
    if employee:
        _render_home(employee)
    else:
        _render_login()


main()
