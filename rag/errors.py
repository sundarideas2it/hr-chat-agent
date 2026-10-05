"""User-facing failures for policy ingestion and answers."""

from __future__ import annotations

import os


class PolicyRagError(Exception):
    """A policy retrieval or answer failure that can be shown to the user."""


def public_error_message(exc: Exception) -> str:
    """Return an error string that does not include the API key."""
    message = str(exc).strip() or "The policy assistant could not complete the request."
    secret = os.environ.get("GOOGLE_API_KEY")
    if secret:
        message = message.replace(secret, "[REDACTED]")
    if "RESOURCE_EXHAUSTED" in message or "quota" in message.lower():
        return (
            "The Gemini API quota has been reached for the configured model. "
            "Wait and try the question again later."
        )
    if "NOT_FOUND" in message and "model" in message.lower():
        return (
            "The configured Gemini model is not available. "
            "Update the chat model in rag/config.py."
        )
    return message
