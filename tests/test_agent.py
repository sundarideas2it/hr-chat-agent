"""LangGraph routing and tool integration without live Gemini calls."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from database.db import get_connection
from database.seed import DEMO_PASSWORD, seed
from agent.graph import build_graph, run_agent
from agent.prompts import CROSS_EMPLOYEE_REFUSAL, POLICY_QUOTA_UNAVAILABLE
from tools.leave_balance import get_leave_balance, get_leave_history


def _employee(code: str) -> dict:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, employee_code, name, department
            FROM employees
            WHERE employee_code = ?
            """,
            (code,),
        ).fetchone()
    if row is None:
        raise AssertionError(f"Missing {code}")
    return {
        "id": int(row["id"]),
        "employee_code": row["employee_code"],
        "name": row["name"],
        "department": row["department"],
    }


class AgentGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        seed()
        cls.employee = _employee("EMP001")
        cls.other = _employee("EMP002")

    def test_graph_has_the_hr_workflow_nodes(self) -> None:
        nodes = set(build_graph().get_graph().nodes)
        self.assertTrue(
            {
                "select_intent",
                "policy_retrieval",
                "leave_balance",
                "leave_history",
                "leave_calculation",
                "eligibility",
                "holiday_lookup",
                "respond",
            }.issubset(nodes)
        )

    def test_casual_leave_balance_uses_the_signed_in_employee(self) -> None:
        with patch("agent.graph.get_leave_balance", wraps=get_leave_balance) as balance:
            result = run_agent("What is my casual leave balance?", self.employee)
        balance.assert_called_once()
        self.assertEqual(balance.call_args.args[0], self.employee["id"])
        self.assertEqual(result["tools_used"], ["Leave Balance"])
        self.assertIn("Entitled: 6 days", result["reply"])
        self.assertIn("Used: 2 days", result["reply"])
        self.assertIn("Remaining: 4 days", result["reply"])
        self.assertNotIn("EMP002", result["reply"])
        self.assertNotIn("Vismitha", result["reply"])

    def test_leave_history_is_only_emp001(self) -> None:
        with patch("agent.graph.get_leave_history", wraps=get_leave_history) as history:
            result = run_agent("Show my leave history.", self.employee)
        history.assert_called_once()
        self.assertEqual(history.call_args.args[0], self.employee["id"])
        self.assertEqual(result["tools_used"], ["Leave History"])
        self.assertIn("9 February 2026", result["reply"])
        self.assertNotIn("6 April 2026", result["reply"])
        self.assertNotIn("14 September 2026", result["reply"])
        self.assertNotIn("EMP002", result["reply"])
        self.assertNotIn("EMP003", result["reply"])

    def test_other_employee_private_data_is_refused(self) -> None:
        with (
            patch("agent.graph.get_leave_balance", wraps=get_leave_balance) as balance,
            patch("agent.graph.get_leave_history", wraps=get_leave_history) as history,
        ):
            vismitha = run_agent("Show Vismitha's leave balance.", self.employee)
            other = run_agent("What is EMP002's leave history?", self.employee)
        balance.assert_not_called()
        history.assert_not_called()
        self.assertEqual(vismitha["reply"], CROSS_EMPLOYEE_REFUSAL)
        self.assertEqual(other["reply"], CROSS_EMPLOYEE_REFUSAL)
        self.assertEqual(vismitha["tools_used"], [])
        self.assertEqual(other["tools_used"], [])
        self.assertNotIn("3 days", vismitha["reply"])

    def test_own_employee_code_still_reads_emp001(self) -> None:
        result = run_agent("What is EMP001's casual leave balance?", self.employee)
        self.assertIn("Remaining: 4 days", result["reply"])
        self.assertEqual(result["tools_used"], ["Leave Balance"])

    def test_date_range_calculation_follows_the_policy(self) -> None:
        result = run_agent(
            "How many leave days will be deducted from 24 January to 27 January 2026?",
            self.employee,
        )
        self.assertEqual(result["tools_used"], ["Leave Calculator"])
        self.assertIn("4 calendar days", result["reply"])
        self.assertIn("Republic Day is excluded as a public holiday.", result["reply"])
        self.assertIn("Saturday and Sunday are excluded as weekly offs.", result["reply"])
        self.assertIn("Chargeable leave: 1 day.", result["reply"])
        self.assertNotIn("section 7.3", result["reply"])
        self.assertNotIn("Rule:", result["reply"])
        self.assertNotIn("no weekend assumption was applied", result["reply"])

    def test_one_day_leave_then_casual_uses_that_date(self) -> None:
        first = run_agent("Can I take leave on 19 oct?", self.employee)
        self.assertIn("which leave type", first["reply"].lower())
        self.assertEqual(first["context"]["start_date"], "2026-10-19")
        self.assertEqual(first["context"]["end_date"], "2026-10-19")
        history = [
            {
                "role": "user",
                "content": "Can I take leave from 11 October 2026 to 12 October 2026?",
            },
            {
                "role": "assistant",
                "content": "Tell me which leave type you mean, such as Casual Leave or Sick Leave.",
                "context": {
                    "intent": "eligibility",
                    "leave_type": None,
                    "start_date": "2026-10-11",
                    "end_date": "2026-10-12",
                    "requested_days": None,
                    "year": 2026,
                    "month": 10,
                },
            },
            {"role": "user", "content": "Can I take leave on 19 oct?"},
            {
                "role": "assistant",
                "content": first["reply"],
                "context": first["context"],
            },
        ]
        result = run_agent("cASUAL", self.employee, history=history)
        self.assertEqual(result["context"]["leave_type"], "CL")
        self.assertEqual(result["context"]["start_date"], "2026-10-19")
        self.assertEqual(result["context"]["end_date"], "2026-10-19")
        self.assertIn("19 October 2026", result["reply"])
        self.assertIn("Ayudha Poojai", result["reply"])
        self.assertIn("Chargeable leave: 0 days.", result["reply"])
        self.assertNotIn("11–12 October", result["reply"])
        self.assertNotIn("12 October", result["reply"])

    def test_leave_type_reply_keeps_the_dates_just_asked(self) -> None:
        first = run_agent(
            "Can I take leave from 10 October 2026 to 11 October 2026?",
            self.employee,
        )
        self.assertIn("which leave type", first["reply"].lower())
        history = [
            {
                "role": "user",
                "content": "Can I take leave from 10 October 2026 to 11 October 2026?",
            },
            {
                "role": "assistant",
                "content": first["reply"],
                "context": first["context"],
            },
        ]
        result = run_agent("casual leave", self.employee, history=history)
        self.assertEqual(result["context"]["leave_type"], "CL")
        self.assertEqual(result["context"]["start_date"], "2026-10-10")
        self.assertEqual(result["context"]["end_date"], "2026-10-11")
        self.assertIn("Chargeable leave: 0 days.", result["reply"])
        self.assertIn("No Casual Leave is charged.", result["reply"])
        self.assertNotIn("I can help with your leave balance", result["reply"])

        lost = run_agent("casual leave", self.employee, history=history + [
            {"role": "user", "content": "casual leave"},
            {
                "role": "assistant",
                "content": "I can help with your leave balance, leave history, leave-day calculations, leave eligibility, and HR policy questions.",
                "context": {"intent": "unknown"},
            },
        ])
        self.assertEqual(lost["context"]["start_date"], "2026-10-10")
        self.assertIn("No Casual Leave is charged.", lost["reply"])

    def test_weekend_casual_leave_is_not_charged(self) -> None:
        result = run_agent(
            "Can I take casual leave from 10 October to 11 October 2026?",
            self.employee,
        )
        self.assertIn("2 calendar days", result["reply"])
        self.assertIn("Saturday and Sunday are excluded as weekly offs.", result["reply"])
        self.assertIn("Chargeable leave: 0 days.", result["reply"])
        self.assertIn("No Casual Leave is charged.", result["reply"])
        self.assertNotIn("requires 2", result["reply"])
        self.assertNotIn("you are eligible", result["reply"].lower())
        self.assertNotIn("not eligible", result["reply"].lower())

    def test_eligibility_for_the_january_range_is_within_balance(self) -> None:
        result = run_agent(
            "Can I take casual leave from 24 January to 27 January 2026?",
            self.employee,
        )
        self.assertEqual(
            result["tools_used"],
            ["Leave Calculator", "Leave Balance", "Eligibility Checker"],
        )
        self.assertIn("requires 1 chargeable day", result["reply"])
        self.assertIn("You have 4 days of Casual Leave remaining", result["reply"])
        self.assertIn("you are eligible based on the available balance", result["reply"])
        self.assertIn("Eligibility does not mean the leave is approved", result["reply"])
        self.assertIn("manager approval", result["reply"].lower())
        self.assertNotIn("not eligible", result["reply"].lower())
        self.assertEqual(result["context"]["leave_type"], "CL")
        self.assertEqual(result["context"]["requested_days"], 1)

    def test_follow_up_for_five_days_is_not_eligible(self) -> None:
        first = run_agent(
            "Can I take casual leave from 24 January to 27 January 2026?",
            self.employee,
        )
        history = [
            {
                "role": "user",
                "content": "Can I take casual leave from 24 January to 27 January 2026?",
            },
            {
                "role": "assistant",
                "content": first["reply"],
                "context": first["context"],
                "tools_used": first["tools_used"],
            },
        ]
        result = run_agent("What about 5 days?", self.employee, history=history)
        self.assertIn("Eligibility Checker", result["tools_used"])
        self.assertNotIn("Leave Calculator", result["tools_used"])
        self.assertIn("not eligible", result["reply"].lower())
        self.assertIn("insufficient", result["reply"].lower())
        self.assertIn("5 days", result["reply"])
        self.assertIn("4 days", result["reply"])
        self.assertIn("manager approval", result["reply"].lower())

    def test_sick_leave_follow_up_uses_the_previous_balance_question(self) -> None:
        first = run_agent("What is my casual leave balance?", self.employee)
        history = [
            {"role": "user", "content": "What is my casual leave balance?"},
            {
                "role": "assistant",
                "content": first["reply"],
                "context": first["context"],
            },
        ]
        result = run_agent("What about sick leave?", self.employee, history=history)
        self.assertEqual(result["tools_used"], ["Leave Balance"])
        self.assertEqual(result["context"]["leave_type"], "SL")
        self.assertIn("Sick Leave", result["reply"])
        self.assertIn("Entitled: 6 days", result["reply"])
        self.assertIn("Used: 2 days", result["reply"])
        self.assertIn("Remaining: 4 days", result["reply"])

    def test_salary_is_not_invented(self) -> None:
        result = run_agent("What is my salary?", self.employee)
        self.assertEqual(result["tools_used"], [])
        self.assertIn("not available", result["reply"].lower())
        self.assertNotRegex(result["reply"], r"\d")
        self.assertNotIn("rupee", result["reply"].lower())

    def test_policy_question_uses_search_without_a_live_model(self) -> None:
        matches = [
            {
                "content": "6 days of Casual Leave (CL) per calendar year.",
                "source": "Revised Leave Policy - I2I.pdf",
                "page": 8,
            }
        ]
        answer = {
            "answer": "Casual Leave is 6 days per calendar year.",
            "sources": ["Revised Leave Policy - I2I.pdf — Page 8"],
            "found": True,
            "matches": matches,
        }
        with (
            patch("agent.graph.search_hr_policy", return_value=matches) as search,
            patch("agent.graph.answer_policy_question", return_value=answer) as model,
            patch("rag.answer.ChatGoogleGenerativeAI") as chat,
        ):
            result = run_agent("What is the casual leave policy?", self.employee)
            wfh = run_agent("What is the work from home policy?", self.employee)
        search.assert_called()
        model.assert_called()
        chat.assert_not_called()
        self.assertEqual(result["tools_used"], ["Policy Search"])
        self.assertIn("6 days", result["reply"])
        self.assertIn("Page 8", result["reply"])
        self.assertEqual(wfh["tools_used"], ["Policy Search"])
        self.assertNotIn("Leave Balance", wfh["tools_used"])
        self.assertEqual(model.call_args.kwargs["matches"], matches)

    def test_deterministic_questions_do_not_call_gemini(self) -> None:
        with (
            patch("rag.answer.ChatGoogleGenerativeAI") as chat,
            patch("rag.retriever.GoogleGenerativeAIEmbeddings") as embeddings,
        ):
            run_agent("What is my casual leave balance?", self.employee)
            run_agent("Show my leave history.", self.employee)
            run_agent(
                "How many leave days will be deducted from 24 January to 27 January 2026?",
                self.employee,
            )
            run_agent(
                "Can I take casual leave from 24 January to 27 January 2026?",
                self.employee,
            )
            run_agent("What are the company holidays in January 2026?", self.employee)
            run_agent("Is 26 January 2026 a company holiday?", self.employee)
        chat.assert_not_called()
        embeddings.assert_not_called()

    def test_invalid_and_reversed_dates_are_explained(self) -> None:
        invalid = run_agent(
            "How many leave days will be deducted from 32 January to 2 February 2026?",
            self.employee,
        )
        reversed_range = run_agent(
            "How many leave days will be deducted from 27 January 2026 to 24 January 2026?",
            self.employee,
        )
        self.assertIn("Invalid date", invalid["reply"])
        self.assertEqual(invalid["tools_used"], [])
        self.assertIn("end date", reversed_range["reply"].lower())
        self.assertEqual(reversed_range["tools_used"], ["Leave Calculator"])

    def test_holiday_questions_use_the_official_calendar(self) -> None:
        january = run_agent(
            "What are the company holidays in January 2026?",
            self.employee,
        )
        october = run_agent(
            "What are the planned holidays in October 2026?",
            self.employee,
        )
        republic = run_agent("Is 26 January 2026 a company holiday?", self.employee)
        ordinary = run_agent("Is 24 January 2026 a company holiday?", self.employee)

        self.assertEqual(january["tools_used"], ["Holiday Lookup"])
        self.assertIn("1 January 2026: New Year", january["reply"])
        self.assertIn("15 January 2026: Pongal", january["reply"])
        self.assertIn("26 January 2026: Republic Day", january["reply"])
        self.assertIn("Source: Holiday List - 2026.pdf", january["reply"])
        self.assertNotIn("Labour Day", january["reply"])

        self.assertIn("2 October 2026: Gandhi Jayanthi", october["reply"])
        self.assertIn("19 October 2026: Ayudha Poojai", october["reply"])
        self.assertNotIn("Diwali", october["reply"])

        self.assertIn("Yes. 26 January 2026 is Republic Day", republic["reply"])
        self.assertIn("Source: Holiday List - 2026.pdf", republic["reply"])
        self.assertIn("not on the company holiday list", ordinary["reply"])

    def test_saturday_rule_question_stays_on_policy_search(self) -> None:
        with (
            patch("agent.graph.search_hr_policy", return_value=[{"content": "weekly off"}]) as search,
            patch(
                "agent.graph.answer_policy_question",
                return_value={
                    "answer": "The holiday list says mandatory leave is enforced on Saturdays and Sundays.",
                    "sources": ["Holiday List - 2026.pdf — Page 1"],
                    "found": True,
                    "matches": [],
                },
            ),
        ):
            result = run_agent(
                "Why does the policy require mandatory leave on Saturdays and Sundays?",
                self.employee,
            )
        search.assert_called_once()
        self.assertEqual(result["tools_used"], ["Policy Search"])
        self.assertNotIn("Holiday Lookup", result["tools_used"])

    def test_demo_questions_stay_deterministic_when_gemini_is_unavailable(self) -> None:
        with (
            patch("rag.answer.ChatGoogleGenerativeAI") as chat,
            patch("rag.retriever.GoogleGenerativeAIEmbeddings") as embeddings,
        ):
            balance = run_agent("How many casual leaves do I have?", self.employee)
            remaining = run_agent("How many CL days are remaining?", self.employee)
            history = run_agent("What leaves have I taken?", self.employee)
            previous = run_agent("Show my previous leaves.", self.employee)
            january = run_agent(
                "What are the company holidays in January 2026?",
                self.employee,
            )
            republic = run_agent("Is 26 January 2026 a holiday?", self.employee)
            year_list = run_agent("Show 2026 holidays.", self.employee)
            october = run_agent("What holidays are there in October?", self.employee)
            eligibility = run_agent(
                "Can I take Casual Leave from 24 Jan to 27 Jan 2026?",
                self.employee,
            )
            follow_up = run_agent(
                "What about 5 days?",
                self.employee,
                history=[
                    {
                        "role": "user",
                        "content": "Can I take Casual Leave from 24 Jan to 27 Jan 2026?",
                    },
                    {
                        "role": "assistant",
                        "content": eligibility["reply"],
                        "context": eligibility["context"],
                    },
                ],
            )
            blocked = run_agent("Show Vismitha's leave balance.", self.employee)
        chat.assert_not_called()
        embeddings.assert_not_called()

        self.assertEqual(balance["tools_used"], ["Leave Balance"])
        self.assertIn("Entitled: 6 days", balance["reply"])
        self.assertIn("Used: 2 days", balance["reply"])
        self.assertIn("Remaining: 4 days", balance["reply"])
        self.assertIn("Remaining: 4 days", remaining["reply"])
        self.assertEqual(remaining["context"]["leave_type"], "CL")

        self.assertEqual(history["tools_used"], ["Leave History"])
        self.assertIn("9 February 2026", history["reply"])
        self.assertNotIn("6 April 2026", history["reply"])
        self.assertNotIn("EMP002", history["reply"])
        self.assertIn("9 February 2026", previous["reply"])

        self.assertEqual(january["tools_used"], ["Holiday Lookup"])
        self.assertIn("New Year", january["reply"])
        self.assertIn("Pongal", january["reply"])
        self.assertIn("Republic Day", january["reply"])
        self.assertIn("Source: Holiday List - 2026.pdf", january["reply"])
        self.assertIn("Yes. 26 January 2026 is Republic Day", republic["reply"])
        self.assertIn("New Year", year_list["reply"])
        self.assertIn("Diwali", year_list["reply"])
        self.assertIn("Gandhi Jayanthi", october["reply"])
        self.assertIn("Ayudha Poojai", october["reply"])
        self.assertNotIn("Diwali", october["reply"])

        self.assertEqual(
            eligibility["tools_used"],
            ["Leave Calculator", "Leave Balance", "Eligibility Checker"],
        )
        self.assertIn("4 calendar days", eligibility["reply"])
        self.assertIn("Republic Day is excluded as a public holiday.", eligibility["reply"])
        self.assertIn("Saturday and Sunday are excluded as weekly offs.", eligibility["reply"])
        self.assertIn("Chargeable leave: 1 day.", eligibility["reply"])
        self.assertIn("you are eligible based on the available balance", eligibility["reply"])
        self.assertNotIn("no weekend assumption was applied", eligibility["reply"])
        self.assertIn("manager approval", eligibility["reply"].lower())
        self.assertIn("not eligible", follow_up["reply"].lower())
        self.assertIn("insufficient", follow_up["reply"].lower())
        self.assertIn("5 days", follow_up["reply"])
        self.assertNotIn("Leave Calculator", follow_up["tools_used"])

        self.assertEqual(blocked["reply"], CROSS_EMPLOYEE_REFUSAL)
        self.assertEqual(blocked["tools_used"], [])

    def test_policy_quota_failure_does_not_invent_an_answer(self) -> None:
        raw = (
            "429 RESOURCE_EXHAUSTED: Quota exceeded. "
            "API key AIzaSyFAKEKEY leaked in the provider payload."
        )
        with (
            patch("agent.graph.search_hr_policy", side_effect=RuntimeError(raw)) as search,
            patch("agent.graph.answer_policy_question") as answer,
            patch("rag.answer.ChatGoogleGenerativeAI") as chat,
        ):
            result = run_agent("What is the Casual Leave policy?", self.employee)
        search.assert_called_once()
        answer.assert_not_called()
        chat.assert_not_called()
        self.assertEqual(result["reply"], POLICY_QUOTA_UNAVAILABLE)
        self.assertNotIn("RESOURCE_EXHAUSTED", result["reply"])
        self.assertNotIn("AIza", result["reply"])
        self.assertNotIn("Traceback", result["reply"])
        self.assertNotIn("6 days", result["reply"])

    def test_logout_clears_chat_history(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=30)
        app.run()
        app.text_input[0].set_value("EMP001")
        app.text_input[1].set_value(DEMO_PASSWORD)
        app.button[0].click().run()
        self.assertEqual(app.session_state["employee"]["employee_code"], "EMP001")

        app.chat_input[0].set_value("What is my casual leave balance?").run()
        visible = " ".join(widget.value for widget in app.markdown)
        self.assertIn("Remaining: 4 days", visible)
        self.assertIn("Leave Balance", visible)
        self.assertNotIn("EMP002", visible)
        self.assertNotIn("Vismitha", visible)
        self.assertGreaterEqual(len(app.session_state["messages"]), 2)

        next(button for button in app.button if button.label == "Logout").click().run()
        self.assertIsNone(app.session_state["employee"])
        self.assertNotIn("messages", app.session_state)
        self.assertTrue(any(widget.label == "Employee ID" for widget in app.text_input))


if __name__ == "__main__":
    unittest.main()
