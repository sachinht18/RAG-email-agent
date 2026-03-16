from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from email_sdr_flow.errors import InputValidationError, RetrievalError
from email_sdr_flow.input_validation import ensure_existing_directory
from email_sdr_flow.runtime import log_event
from email_sdr_flow.schemas import GroundingSnippet


ALLOWED_EXTENSIONS = {".md", ".txt"}


@dataclass(slots=True)
class KnowledgeBaseDiagnostics:
    source_type: str
    directory: str
    supported_file_count: int
    loaded_file_count: int
    empty_files: list[str] = field(default_factory=list)
    ignored_file_count: int = 0
    chunk_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalDiagnostics:
    source_type: str
    query: str
    hit_count: int
    source_paths: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class KnowledgeBase:
    name: str
    directory: Path
    retriever: object
    diagnostics: KnowledgeBaseDiagnostics


def _scan_documents(directory: Path, source_type: str) -> tuple[list[Document], KnowledgeBaseDiagnostics]:
    ensure_existing_directory(directory, label=f"{source_type} knowledge")

    documents: list[Document] = []
    supported_file_count = 0
    ignored_file_count = 0
    empty_files: list[str] = []

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            ignored_file_count += 1
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            ignored_file_count += 1
            continue

        supported_file_count += 1
        try:
            text = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError as exc:
            raise InputValidationError(
                code="invalid_document_encoding",
                message=f"{source_type} document could not be decoded as UTF-8.",
                context={"path": str(path)},
            ) from exc

        if not text:
            empty_files.append(str(path))
            continue

        documents.append(
            Document(
                page_content=text,
                metadata={
                    "source_type": source_type,
                    "source_path": str(path),
                    "title": path.stem.replace("_", " ").replace("-", " "),
                },
            )
        )

    if supported_file_count == 0:
        raise InputValidationError(
            code="no_supported_documents",
            message=(
                f"No supported {source_type} documents were found. "
                f"Add at least one {', '.join(sorted(ALLOWED_EXTENSIONS))} file."
            ),
            context={"directory": str(directory)},
        )
    if not documents:
        raise InputValidationError(
            code="only_empty_documents",
            message=(
                f"Supported {source_type} documents were found, but all were empty. "
                "Add content before running the workflow."
            ),
            context={"directory": str(directory), "empty_files": empty_files},
        )

    warnings: list[str] = []
    if empty_files:
        warnings.append(
            f"Ignored {len(empty_files)} empty {source_type} document(s)."
        )

    diagnostics = KnowledgeBaseDiagnostics(
        source_type=source_type,
        directory=str(directory),
        supported_file_count=supported_file_count,
        loaded_file_count=len(documents),
        empty_files=empty_files,
        ignored_file_count=ignored_file_count,
        warnings=warnings,
    )
    log_event(
        "knowledge.loaded",
        source_type=source_type,
        directory=str(directory),
        supported_files=supported_file_count,
        loaded_files=len(documents),
        empty_files=len(empty_files),
        ignored_files=ignored_file_count,
    )
    return documents, diagnostics


def load_source_documents(
    directory: str | Path,
    *,
    source_type: str,
) -> list[Document]:
    documents, _ = _scan_documents(Path(directory), source_type=source_type)
    return documents


def build_knowledge_base(
    directory: str | Path,
    *,
    source_type: str,
    embeddings: Embeddings,
    chunk_size: int = 900,
    chunk_overlap: int = 120,
    k: int = 4,
) -> KnowledgeBase:
    base_path = Path(directory)
    documents, diagnostics = _scan_documents(base_path, source_type=source_type)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    split_documents = splitter.split_documents(documents)
    diagnostics.chunk_count = len(split_documents)
    if diagnostics.chunk_count < 2:
        diagnostics.warnings.append(
            f"{source_type} corpus is very small. Retrieval quality may be weak."
        )
    store = InMemoryVectorStore(embedding=embeddings)
    store.add_documents(split_documents)
    retriever = store.as_retriever(search_kwargs={"k": k})
    return KnowledgeBase(
        name=source_type,
        directory=base_path,
        retriever=retriever,
        diagnostics=diagnostics,
    )


def retrieve_documents(
    kb: KnowledgeBase,
    query: str,
    *,
    minimum_hits: int = 1,
) -> tuple[list[Document], RetrievalDiagnostics]:
    try:
        documents = list(kb.retriever.invoke(query))
    except Exception as exc:
        raise RetrievalError(
            code="retrieval_invoke_failed",
            message=f"{kb.name} retrieval failed.",
            context={"query": query, "directory": str(kb.directory), "error": str(exc)},
        ) from exc

    source_paths = [str(doc.metadata.get("source_path", "")) for doc in documents]
    warnings: list[str] = []
    if len(documents) < minimum_hits:
        raise RetrievalError(
            code="retrieval_no_hits",
            message=f"{kb.name} retrieval returned no usable snippets.",
            context={"query": query, "directory": str(kb.directory)},
        )
    if len(documents) < 2:
        warnings.append(f"{kb.name} retrieval returned only {len(documents)} snippet(s).")

    diagnostics = RetrievalDiagnostics(
        source_type=kb.name,
        query=query,
        hit_count=len(documents),
        source_paths=source_paths,
        warnings=warnings,
    )
    log_event(
        "retrieval.success",
        source_type=kb.name,
        query=query,
        hit_count=len(documents),
        source_paths=source_paths,
    )
    return documents, diagnostics


def docs_to_snippets(documents: list[Document]) -> list[GroundingSnippet]:
    snippets: list[GroundingSnippet] = []
    for document in documents:
        excerpt = document.page_content[:700].strip()
        if not excerpt:
            continue
        snippets.append(
            GroundingSnippet(
                source_type=document.metadata["source_type"],
                title=document.metadata["title"],
                source_path=document.metadata["source_path"],
                excerpt=excerpt,
            )
        )
    if not snippets:
        raise RetrievalError(
            code="retrieval_empty_snippets",
            message="Retrieved documents did not contain usable snippet content.",
            context={},
        )
    return snippets


def format_snippets(snippets: list[GroundingSnippet]) -> str:
    if not snippets:
        return "No grounding snippets retrieved."

    blocks = []
    for index, snippet in enumerate(snippets, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[{index}] {snippet.title}",
                    f"source_type: {snippet.source_type}",
                    f"source_path: {snippet.source_path}",
                    f"excerpt: {snippet.excerpt}",
                ]
            )
        )
    return "\n\n".join(blocks)


def format_documents_for_review(
    documents: list[Document],
    *,
    max_chars_per_doc: int = 2200,
) -> str:
    if not documents:
        return "No documents available."

    blocks = []
    for index, document in enumerate(documents, start=1):
        excerpt = document.page_content[:max_chars_per_doc].strip()
        blocks.append(
            "\n".join(
                [
                    f"[{index}] {document.metadata.get('title', 'untitled')}",
                    f"source_type: {document.metadata.get('source_type', '')}",
                    f"source_path: {document.metadata.get('source_path', '')}",
                    f"excerpt: {excerpt}",
                ]
            )
        )
    return "\n\n".join(blocks)
