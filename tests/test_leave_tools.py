"""Focused checks for deterministic leave tools and the signed-in UI."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from database.db import get_connection
from database.seed import seed
from tools.eligibility import check_leave_eligibility
from tools.errors import LeaveToolError
from tools.holidays import get_holidays, get_holidays_between
from tools.leave_balance import get_leave_balance, get_leave_history
from tools.leave_calculator import calculate_leave_days


def _employee_id(code: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM employees WHERE employee_code = ?",
            (code,),
        ).fetchone()
        if row is None:
            raise AssertionError(f"Missing {code}")
        return int(row["id"])


class LeaveToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        seed()
        seed()
        cls.emp1 = _employee_id("EMP001")
        cls.emp2 = _employee_id("EMP002")
        cls.emp3 = _employee_id("EMP003")

    def test_emp001_casual_leave_balance(self) -> None:
        result = get_leave_balance(self.emp1, "CL", 2026)
        self.assertEqual(result["employee_code"], "EMP001")
        self.assertEqual(result["balances"][0]["entitled"], 6)
        self.assertEqual(result["balances"][0]["used"], 2)
        self.assertEqual(result["balances"][0]["remaining"], 4)

    def test_all_balances_belong_to_emp001(self) -> None:
        result = get_leave_balance(self.emp1)
        self.assertEqual(result["employee_code"], "EMP001")
        codes = {item["leave_type"] for item in result["balances"]}
        self.assertEqual(codes, {"CL", "EL", "PL", "SL"})
        for item in result["balances"]:
            self.assertGreaterEqual(item["entitled"], item["used"])
            self.assertEqual(item["remaining"], item["entitled"] - item["used"])

    def test_history_is_limited_to_emp001(self) -> None:
        result = get_leave_history(self.emp1)
        self.assertEqual(result["employee_code"], "EMP001")
        self.assertGreaterEqual(len(result["requests"]), 1)
        starts = {item["start_date"] for item in result["requests"]}
        self.assertIn("2026-02-09", starts)
        self.assertNotIn("2026-04-06", starts)
        self.assertNotIn("2026-09-14", starts)

    def test_policy_entitlements_match_the_pdf(self) -> None:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT code, annual_entitlement FROM leave_types ORDER BY code"
            ).fetchall()
            entitlements = {row["code"]: row["annual_entitlement"] for row in rows}
        self.assertEqual(entitlements["CL"], 6)
        self.assertEqual(entitlements["SL"], 6)
        self.assertEqual(entitlements["EL"], 12)
        self.assertEqual(entitlements["PL"], 0)

    def test_invalid_dates_and_reversed_range(self) -> None:
        with self.assertRaises(LeaveToolError):
            calculate_leave_days("2026-02-31", "2026-03-01")
        with self.assertRaises(LeaveToolError):
            calculate_leave_days("2026-03-02", "2026-03-01")

    def test_holiday_and_weekend_are_excluded(self) -> None:
        result = calculate_leave_days("2026-01-24", "2026-01-27")
        self.assertEqual(result["calendar_days"], 4)
        self.assertEqual(result["chargeable_leave_days"], 1)
        excluded = {item["date"]: item["name"] for item in result["excluded_dates"]}
        self.assertEqual(
            excluded,
            {
                "2026-01-24": "Saturday",
                "2026-01-25": "Sunday",
                "2026-01-26": "Republic Day",
            },
        )
        reasons = {item["date"]: item["reason"] for item in result["excluded_dates"]}
        self.assertEqual(reasons["2026-01-24"], "weekly off")
        self.assertEqual(reasons["2026-01-26"], "public holiday")
        self.assertTrue(any("section 7.3" in rule for rule in result["applied_rules"]))
        self.assertEqual(date(2026, 1, 24).weekday(), 5)

    def test_saturday_and_sunday_are_not_chargeable(self) -> None:
        result = calculate_leave_days("2026-10-10", "2026-10-11")
        self.assertEqual(result["calendar_days"], 2)
        self.assertEqual(result["chargeable_leave_days"], 0)
        self.assertEqual(
            [item["name"] for item in result["excluded_dates"]],
            ["Saturday", "Sunday"],
        )

    def test_holiday_lookup(self) -> None:
        holidays = get_holidays_between("2026-01-01", "2026-01-26")
        names = [item["name"] for item in holidays]
        self.assertEqual(names, ["New Year", "Pongal", "Republic Day"])

    def test_official_2026_holidays_replace_the_demo_calendar(self) -> None:
        seed()
        expected = {
            "2026-01-01": "New Year",
            "2026-01-15": "Pongal",
            "2026-01-26": "Republic Day",
            "2026-03-21": "Ramzan",
            "2026-04-14": "Tamil New Year",
            "2026-05-01": "May Day",
            "2026-08-15": "Independence Day",
            "2026-09-14": "Vinayakar Chathurthi",
            "2026-10-02": "Gandhi Jayanthi",
            "2026-10-19": "Ayudha Poojai",
            "2026-11-08": "Diwali",
            "2026-12-25": "Christmas",
        }
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT holiday_date, name FROM holidays ORDER BY holiday_date"
            ).fetchall()
        actual = {row["holiday_date"]: row["name"] for row in rows}
        self.assertEqual(actual, expected)
        self.assertEqual(len(rows), 12)
        self.assertNotIn("Labour Day", actual.values())
        self.assertNotIn("New Year's Day", actual.values())
        self.assertNotIn("Gandhi Jayanti", actual.values())

        january = get_holidays(2026, 1)
        self.assertEqual(
            [(item["date"], item["name"]) for item in january["holidays"]],
            [
                ("2026-01-01", "New Year"),
                ("2026-01-15", "Pongal"),
                ("2026-01-26", "Republic Day"),
            ],
        )
        self.assertEqual(january["source"], "Holiday List - 2026.pdf")

        from rag.ingest import discover_policy_files

        names = {path.name for path in discover_policy_files()}
        self.assertIn("Holiday List - 2026.pdf", names)
        self.assertIn("Revised Leave Policy - I2I.pdf", names)

    def test_cl_within_balance_is_eligible_but_not_approved(self) -> None:
        result = check_leave_eligibility(self.emp1, "CL", 4)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["remaining_balance"], 4)
        self.assertTrue(any("not approval" in item["rule"].lower() or "not leave approval" in warning.lower() for item in result["policy_constraints"] for warning in result["warnings"]))
        self.assertTrue(any("reporting manager" in warning.lower() for warning in result["warnings"]))

    def test_cl_above_balance_is_not_eligible(self) -> None:
        result = check_leave_eligibility(self.emp1, "CL", 5)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["remaining_balance"], 4)
        balance_check = next(item for item in result["checks"] if item["name"] == "balance")
        self.assertFalse(balance_check["passed"])

    def test_unknown_leave_type(self) -> None:
        result = check_leave_eligibility(self.emp1, "XX", 1)
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["remaining_balance"])

    def test_other_employee_is_a_different_record(self) -> None:
        other = get_leave_balance(self.emp2, "CL")
        self.assertEqual(other["employee_code"], "EMP002")
        self.assertNotEqual(other["balances"][0]["used"], 2)

    def test_ui_has_no_employee_id_field_for_leave_tools(self) -> None:
        from streamlit.testing.v1 import AppTest
        from database.seed import DEMO_PASSWORD

        source = Path("app.py").read_text(encoding="utf-8")
        leave_section = source.split("def _render_leave_tools", 1)[1]
        self.assertIn('employee["id"]', leave_section)
        self.assertNotIn("text_input", leave_section)

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=30)
        app.run()
        app.text_input[0].set_value("EMP001")
        app.text_input[1].set_value(DEMO_PASSWORD)
        app.button[0].click().run()
        self.assertEqual(app.session_state["employee"]["employee_code"], "EMP001")
        self.assertFalse(any(widget.label == "Employee ID" for widget in app.text_input))

        next(button for button in app.button if button.label == "My Leave Balances").click().run()
        visible = " ".join(widget.value for widget in app.markdown)
        self.assertIn("EMP001", visible)
        self.assertIn("remaining 4", visible)
        self.assertNotIn("EMP002", visible)
        self.assertNotIn("EMP003", visible)

        next(button for button in app.button if button.label == "Check Eligibility").click().run()
        visible = " ".join(widget.value for widget in app.markdown)
        self.assertIn("Eligible", visible)
        self.assertNotIn("Not eligible", visible)
        self.assertIn("reporting manager", visible.lower())


if __name__ == "__main__":
    unittest.main()
