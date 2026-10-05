"""Shared settings for HR policy retrieval and grounded answers."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from rag.errors import PolicyRagError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICIES_DIR = PROJECT_ROOT / "policies"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "hr_policies"

# Current text embedding model listed by the installed langchain-google-genai
# package and available on the Gemini Developer API.
EMBEDDING_MODEL = "gemini-embedding-2"

# Gemini chat model available to this API key.
# gemini-2.5-flash is closed to new users. gemini-3.8-flash is available but
# its free-tier daily request cap is easy to exhaust, so answers use 3.7 Flash.
CHAT_MODEL = "gemini-3.7-flash"

CHUNK_SIZE = 900
CHUNK_OVERLAP = 120

NOT_FOUND_MESSAGE = (
    "I couldn't find this information in the available HR policy documents."
)


def load_api_key() -> str:
    """Load GOOGLE_API_KEY from the environment or the project .env file."""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise PolicyRagError(
            "GOOGLE_API_KEY is not set. Add it to the .env file and try again."
        )
    return api_key
