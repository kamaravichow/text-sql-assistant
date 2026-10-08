"""Schema retrieval (the "R" in RAG) over hand-written table documentation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langsmith import traceable
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Joins are the usual failure mode of text-to-SQL, so retrieved tables pull in their FK neighbours.
MAX_EXPANSION = 2


@dataclass
class TableDoc:
    name: str
    text: str
    related: list[str] = field(default_factory=list)


def load_table_docs(docs_dir: Path) -> list[TableDoc]:
    """Each ``*.md`` file documents one table: ``# name`` heading + optional ``Related tables:``."""
    docs: list[TableDoc] = []
    for path in sorted(Path(docs_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        heading = re.search(r"^#\s+(\S+)", text, flags=re.MULTILINE)
        name = heading.group(1) if heading else path.stem
        rel = re.search(r"\*\*Related tables:\*\*\s*(.+)", text)
        related = [r.strip() for r in rel.group(1).split(",")] if rel else []
        docs.append(TableDoc(name=name, text=text, related=related))
    if not docs:
        raise FileNotFoundError(f"No table documentation found in {docs_dir}")
    return docs


class Retriever(Protocol):
    def scores(self, question: str) -> list[tuple[TableDoc, float]]: ...


class TfidfRetriever:
    """Dependency-free lexical retrieval; works offline and is easy to reason about."""

    def __init__(self, docs: list[TableDoc]):
        self.docs = docs
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
            token_pattern=r"(?u)\b[a-zA-Z_][a-zA-Z0-9_]+\b",
        )
        self.matrix = self.vectorizer.fit_transform([d.text for d in docs])

    def scores(self, question: str) -> list[tuple[TableDoc, float]]:
        sims = cosine_similarity(self.vectorizer.transform([question]), self.matrix)[0]
        return sorted(zip(self.docs, sims, strict=True), key=lambda p: p[1], reverse=True)


class EmbeddingRetriever:
    """Semantic retrieval with any LangChain ``Embeddings`` implementation."""

    def __init__(self, docs: list[TableDoc], embeddings: Embeddings):
        self.docs = {d.name: d for d in docs}
        self.store = InMemoryVectorStore(embeddings)
        self.store.add_documents(
            [Document(page_content=d.text, metadata={"table": d.name}) for d in docs]
        )

    def scores(self, question: str) -> list[tuple[TableDoc, float]]:
        hits = self.store.similarity_search_with_score(question, k=len(self.docs))
        return [(self.docs[d.metadata["table"]], float(s)) for d, s in hits]


class SchemaRetriever:
    """Rank table docs for a question, then add the joinable neighbours of the best hits."""

    def __init__(self, docs: list[TableDoc], backend: Retriever, top_k: int = 3):
        self.docs = {d.name: d for d in docs}
        self.backend = backend
        self.top_k = top_k

    @traceable(name="retrieve_tables", run_type="retriever")
    def retrieve(self, question: str) -> list[TableDoc]:
        ranked = [d for d, _ in self.backend.scores(question)]
        selected = ranked[: self.top_k]
        names = {d.name for d in selected}
        added = 0
        for doc in list(selected):
            for rel in doc.related:
                if rel in self.docs and rel not in names and added < MAX_EXPANSION:
                    selected.append(self.docs[rel])
                    names.add(rel)
                    added += 1
        return selected

    def all_tables(self) -> list[str]:
        return sorted(self.docs)


def build_retriever(settings, embeddings: Embeddings | None = None) -> SchemaRetriever:
    docs = load_table_docs(settings.docs_dir)
    if settings.retrieval_backend == "embeddings":
        if embeddings is None:
            from .llm import build_embeddings

            embeddings = build_embeddings(settings)
        backend: Retriever = EmbeddingRetriever(docs, embeddings)
    else:
        backend = TfidfRetriever(docs)
    return SchemaRetriever(docs, backend, top_k=settings.retrieval_top_k)
