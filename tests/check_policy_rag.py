"""Manual check of grounded HR policy answers.

Run after ingestion:

    python -m tests.check_policy_rag
"""

from __future__ import annotations

from rag.answer import answer_policy_question
from rag.config import NOT_FOUND_MESSAGE
from rag.errors import PolicyRagError, public_error_message

# The indexed policy is the PDF in policies/. These checks follow that document.
# question, required phrases, mode
# mode "found" requires those phrases and a PDF citation.
# mode "absent" requires the not-found sentence.
# mode "no-thirty" allows a grounded privilege-leave answer, but not a 30-day rule.
_CHECKS = (
    (
        "How many casual leave days do employees receive annually?",
        ("6", "casual"),
        "found",
    ),
    (
        "When is a medical certificate required for sick leave?",
        (),
        "absent",
    ),
    (
        "Can privilege leave be carried forward?",
        (),
        "no-thirty",
    ),
    (
        "How many days can employees work from home per week?",
        (),
        "absent",
    ),
    (
        "What is the company car allowance policy?",
        (),
        "absent",
    ),
)

_INVENTED_CLAIMS = (
    "more than 2 consecutive",
    "up to 30 days",
    "2 days per week",
    "car allowance is",
    "car allowance of",
)


def main() -> None:
    failures = 0
    for number, (question, phrases, mode) in enumerate(_CHECKS, start=1):
        print(f"\n{number}. {question}")
        try:
            result = answer_policy_question(question)
        except PolicyRagError as exc:
            print(f"ERROR: {public_error_message(exc)}")
            failures += 1
            continue

        answer_text = result["answer"].lower()
        print(f"Answer: {result['answer']}")
        print("Retrieved sources:")
        if not result["matches"]:
            print("- none")
        for match in result["matches"]:
            print(
                "- "
                f"{match.get('source')} "
                f"section={match.get('section')} "
                f"page={match.get('page')} "
                f"relevance={match.get('relevance')}"
            )

        invented = any(claim in answer_text for claim in _INVENTED_CLAIMS)
        cited_pdf = any(
            str(citation).lower().endswith(".pdf") or "page" in str(citation).lower()
            for citation in result["sources"]
        )
        refused = NOT_FOUND_MESSAGE.lower() in answer_text and not result["found"]
        if mode == "found":
            missing = [phrase for phrase in phrases if phrase.lower() not in answer_text]
            if missing or not result["found"] or not cited_pdf or invented:
                print("FAIL: expected the indexed leave policy and a PDF citation.")
                failures += 1
            else:
                print("PASS")
        elif mode == "no-thirty":
            if "30" in answer_text or invented:
                print("FAIL: the policy does not state a 30-day privilege-leave carry-forward.")
                failures += 1
            elif refused or (result["found"] and cited_pdf):
                print("PASS")
            else:
                print("FAIL: expected a refusal or a cited policy answer.")
                failures += 1
        elif not refused or invented:
            print("FAIL: this rule is not in the indexed policy and must not be invented.")
            failures += 1
        else:
            print("PASS")

    if failures:
        raise SystemExit(f"\n{failures} policy check(s) failed.")
    print("\nAll 5 policy checks passed.")


if __name__ == "__main__":
    main()
