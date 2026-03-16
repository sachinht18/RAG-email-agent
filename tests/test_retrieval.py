from __future__ import annotations

import pytest
from email_sdr_flow.errors import InputValidationError, RetrievalError
from email_sdr_flow.retrieval import build_knowledge_base, docs_to_snippets
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


def test_build_knowledge_base_rejects_only_empty_documents(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "empty.md").write_text("", encoding="utf-8")

    embeddings = FakeEmbeddings()

    with pytest.raises(InputValidationError) as exc_info:
        build_knowledge_base(docs_dir, source_type="product_docs", embeddings=embeddings)

    assert exc_info.value.code == "only_empty_documents"


def test_build_knowledge_base_rejects_missing_supported_documents(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "notes.pdf").write_text("unsupported", encoding="utf-8")

    embeddings = FakeEmbeddings()

    with pytest.raises(InputValidationError) as exc_info:
        build_knowledge_base(docs_dir, source_type="product_docs", embeddings=embeddings)

    assert exc_info.value.code == "no_supported_documents"


def test_build_knowledge_base_reports_partial_corpus_warnings(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "valid.md").write_text("Some useful content.", encoding="utf-8")
    (docs_dir / "empty.md").write_text("", encoding="utf-8")

    embeddings = FakeEmbeddings()
    kb = build_knowledge_base(docs_dir, source_type="copywriting", embeddings=embeddings)

    diagnostics = kb.diagnostics.to_dict()
    assert diagnostics["loaded_file_count"] == 1
    assert diagnostics["empty_files"] == [str(docs_dir / "empty.md")]
    assert diagnostics["warnings"]


def test_docs_to_snippets_rejects_empty_retrieved_documents():
    documents = [
        Document(
            page_content="",
            metadata={
                "source_type": "copywriting",
                "source_path": "/tmp/source.md",
                "title": "source",
            },
        )
    ]

    with pytest.raises(RetrievalError) as exc_info:
        docs_to_snippets(documents)

    assert exc_info.value.code == "retrieval_empty_snippets"
