"""Load HR policy files, chunk them, and store embeddings in ChromaDB.

Running this module rebuilds the local ``hr_policies`` collection, so a
second run replaces the previous chunks instead of duplicating them.
"""

from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from rag.config import (
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    POLICIES_DIR,
    load_api_key,
)
from rag.errors import PolicyRagError, public_error_message

_HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "document_title"), ("##", "section")],
    strip_headers=False,
)


def discover_policy_files(directory: Path | None = None) -> list[Path]:
    """Return PDF and Markdown policy files, excluding the folder README."""
    policy_dir = directory or POLICIES_DIR
    if not policy_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(policy_dir.iterdir()):
        if not path.is_file() or path.name.lower() == "readme.md":
            continue
        if path.suffix.lower() in {".pdf", ".md"}:
            files.append(path)
    return files


def load_policy_file(path: Path) -> list[Document]:
    """Load one policy file and keep the filename in metadata."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        documents = PyPDFLoader(str(path)).load()
        for document in documents:
            # PyPDFLoader records a zero-based page index.
            page = document.metadata.get("page")
            if isinstance(page, int):
                document.metadata["page"] = page + 1
    elif suffix == ".md":
        documents = TextLoader(str(path), encoding="utf-8").load()
    else:
        return []

    for document in documents:
        document.metadata["source"] = path.name
    return documents


def split_documents(documents: list[Document]) -> list[Document]:
    """Split policies into overlapping chunks and keep section metadata."""
    prepared: list[Document] = []
    for document in documents:
        source_name = str(document.metadata.get("source", ""))
        if source_name.lower().endswith(".md"):
            sections = _HEADER_SPLITTER.split_text(document.page_content)
            if not sections:
                prepared.append(document)
                continue
            for section in sections:
                section.metadata = {**document.metadata, **section.metadata}
            prepared.extend(sections)
        else:
            prepared.append(document)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(prepared)
    cleaned: list[Document] = []
    for chunk in chunks:
        text = chunk.page_content.strip()
        if not text:
            continue
        chunk.page_content = text
        chunk.metadata = _chroma_metadata(chunk.metadata)
        cleaned.append(chunk)
    return cleaned


def _chroma_metadata(metadata: dict) -> dict:
    """Keep only scalar metadata values Chroma can store."""
    cleaned: dict[str, str | int | float | bool] = {}
    source = metadata.get("source")
    if source:
        cleaned["source"] = Path(str(source)).name
    section = metadata.get("section")
    if section:
        cleaned["section"] = str(section)
    page = metadata.get("page")
    if isinstance(page, int):
        cleaned["page"] = page
    return cleaned


def _reset_collection() -> None:
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    existing = {collection.name for collection in client.list_collections()}
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)


def ingest(directory: Path | None = None) -> dict[str, int]:
    """Rebuild the local policy index and return file and chunk counts."""
    load_api_key()
    files = discover_policy_files(directory)
    if not files:
        raise PolicyRagError(
            "No policy documents found in policies/. Add a PDF or Markdown policy and run ingestion again."
        )

    documents: list[Document] = []
    for path in files:
        documents.extend(load_policy_file(path))
    chunks = split_documents(documents)
    if not chunks:
        raise PolicyRagError("The policy documents did not contain any text to index.")

    try:
        _reset_collection()
        embeddings = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)
        Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=str(CHROMA_DIR),
            collection_name=COLLECTION_NAME,
            collection_metadata={"hnsw:space": "cosine"},
        )
    except PolicyRagError:
        raise
    except Exception as exc:
        raise PolicyRagError(
            "Embedding or vector storage failed. " + public_error_message(exc)
        ) from exc

    return {"files": len(files), "chunks": len(chunks)}


def main() -> None:
    try:
        counts = ingest()
    except PolicyRagError as exc:
        raise SystemExit(public_error_message(exc)) from exc

    print("Policy ingestion complete.")
    print(f"Documents: {counts['files']}")
    print(f"Chunks: {counts['chunks']}")
    print(f"Embedding model: {EMBEDDING_MODEL}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Persist directory: {CHROMA_DIR}")


if __name__ == "__main__":
    main()
