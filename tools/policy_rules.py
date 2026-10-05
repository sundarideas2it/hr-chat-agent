"""Leave rules taken from Revised Leave Policy - I2I.pdf.

These statements were read from the PDF. They are not inferred from the
earlier fictional demo policy. Numeric balances still come from SQLite.
"""

from __future__ import annotations

DEFAULT_LEAVE_YEAR = 2026

POLICY_DOCUMENT = "Revised Leave Policy - I2I.pdf"

# Annual quotas the PDF states explicitly (pages 1, 2, and 8).
POLICY_ANNUAL_ENTITLEMENTS = {
    "CL": 6,
    "SL": 6,
    "EL": 12,
}

LEAVE_TYPE_NOTES = {
    "CL": (
        "Entitlement matches the supplied policy: 6 Casual Leave days per "
        "calendar year (pages 1, 2, and 8). Used days are sample database data."
    ),
    "SL": (
        "Entitlement matches the supplied policy: 6 Sick Leave days per "
        "calendar year (pages 1, 2, and 8). Used days are sample database data."
    ),
    "EL": (
        "Entitlement matches the supplied policy: 12 Earned Leave days per "
        "calendar year (pages 1, 2, and 8). Used days are sample database data."
    ),
    "PL": (
        "Sample retained balance only. The supplied policy does not grant an "
        "annual Privilege Leave quota. Existing PL is a legacy balance that "
        "may remain until used (pages 3-5 and 10)."
    ),
}

# Rules the PDF states in words. None of these replace the balance arithmetic.
VERIFIED_CONSTRAINTS = (
    {
        "leave_types": None,
        "rule": (
            "Every leave request must be submitted in advance and approved by "
            "the reporting manager. Meeting the checks below is not approval."
        ),
        "source": f"{POLICY_DOCUMENT}, section 7.1, page 7; FAQ 15, page 10",
    },
    {
        "leave_types": ("CL",),
        "rule": (
            "Casual Leave is 6 days per calendar year. Unused Casual Leave "
            "cannot be carried forward or encashed."
        ),
        "source": f"{POLICY_DOCUMENT}, section 4.1, pages 1-2; FAQ 4, page 9",
    },
    {
        "leave_types": ("SL",),
        "rule": (
            "Sick Leave is 6 days per calendar year. Unused Sick Leave cannot "
            "be carried forward or encashed."
        ),
        "source": f"{POLICY_DOCUMENT}, section 4.2, pages 1-2; FAQ 5, page 9",
    },
    {
        "leave_types": ("EL",),
        "rule": (
            "Earned Leave is 12 days per calendar year. Up to 8 unused days "
            "can be carried forward, with an accumulation cap of 20 days."
        ),
        "source": f"{POLICY_DOCUMENT}, section 4.3, pages 1-2; FAQ 6-7, page 9",
    },
    {
        "leave_types": ("PL",),
        "rule": (
            "The current policy does not grant a new annual Privilege Leave "
            "entitlement. A recorded PL balance is sample retained data."
        ),
        "source": f"{POLICY_DOCUMENT}, sections 5.1 and FAQ 11-14, pages 3-5 and 10",
    },
)

HOLIDAY_RULE = (
    "A declared public holiday that falls inside the leave period is not "
    f"counted as leave ({POLICY_DOCUMENT}, section 7.3, page 8; FAQ 19, page 11)."
)

HOLIDAY_LIST_DOCUMENT = "Holiday List - 2026.pdf"

WEEKLY_OFF_WARNING = (
    "The leave policy says a weekly off inside the leave period is not counted "
    f"as leave ({POLICY_DOCUMENT}, section 7.3, page 8; FAQ 19, page 11). "
    f"{HOLIDAY_LIST_DOCUMENT} says mandatory leave is enforced on Saturdays and "
    "Sundays. The documents do not explicitly state that a weekly off is "
    "Saturday or Sunday, so Saturday and Sunday were not removed."
)

HOLIDAY_DATA_WARNING = (
    "Public holiday dates in this count come from "
    f"{HOLIDAY_LIST_DOCUMENT}."
)

APPROVAL_WARNING = (
    "Eligibility is not leave approval. The policy still requires advance "
    "approval by the reporting manager."
)


def constraints_for(leave_type_code: str) -> list[dict]:
    """Return verified policy statements that apply to this leave type."""
    code = leave_type_code.upper()
    selected = []
    for constraint in VERIFIED_CONSTRAINTS:
        leave_types = constraint["leave_types"]
        if leave_types is None or code in leave_types:
            selected.append(
                {"rule": constraint["rule"], "source": constraint["source"]}
            )
    return selected
