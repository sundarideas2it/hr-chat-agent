"""Retrieve HR policy evidence from the local Chroma collection.

This module does not call a chat model and does not write an answer.
"""

from __future__ import annotations

import chromadb
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from rag.config import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL, load_api_key
from rag.errors import PolicyRagError, public_error_message


def search_policy(query: str, k: int = 4) -> list[dict]:
    """Return the closest policy chunks for ``query``.

    Each result contains ``content``, ``source``, ``page`` when the loader
    provided one, ``section`` when a Markdown heading was available, and
    ``relevance`` when Chroma returns a score. Higher relevance is closer.
    """
    question = query.strip()
    if not question:
        raise PolicyRagError("Enter a policy question.")
    if k < 1:
        raise PolicyRagError("The number of policy results must be at least 1.")

    load_api_key()
    _require_index()
    try:
        store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=GoogleGenerativeAIEmbeddings(
                model=EMBEDDING_MODEL,
                client_args={"timeout": 30},
            ),
            persist_directory=str(CHROMA_DIR),
        )
        matches = store.similarity_search_with_relevance_scores(question, k=k)
    except PolicyRagError:
        raise
    except Exception as exc:
        raise PolicyRagError(
            "Policy search failed. " + public_error_message(exc)
        ) from exc

    results: list[dict] = []
    for document, score in matches:
        metadata = document.metadata or {}
        page = metadata.get("page")
        results.append(
            {
                "content": document.page_content,
                "source": metadata.get("source"),
                "page": page if isinstance(page, int) else None,
                "section": metadata.get("section"),
                "relevance": score,
            }
        )
    return results


def format_citation(result: dict) -> str:
    """Format one retrieved chunk as a short source citation."""
    source = result.get("source") or "unknown source"
    section = result.get("section")
    page = result.get("page")
    if section:
        return f"{source} — {section}"
    if isinstance(page, int):
        return f"{source} — Page {page}"
    return str(source)


def _require_index() -> None:
    if not CHROMA_DIR.exists():
        raise PolicyRagError(
            "The policy index has not been created. Run: python -m rag.ingest"
        )
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    names = {collection.name for collection in client.list_collections()}
    if COLLECTION_NAME not in names:
        raise PolicyRagError(
            "The policy index has not been created. Run: python -m rag.ingest"
        )
