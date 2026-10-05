"""Policy search tool for the HR Chat Agent.

This wraps the existing retriever. It does not call the chat model and it
does not read employee records.
"""

from __future__ import annotations

from rag.retriever import search_policy


def search_hr_policy(query: str, k: int = 4) -> list[dict]:
    """Return policy passages for a question.

    The result is evidence for an answer. It is not itself an employee record
    and it has no employee id argument.
    """
    return search_policy(query, k=k)
