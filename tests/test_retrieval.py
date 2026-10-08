from conftest import ROOT, make_settings
from langchain_core.embeddings import DeterministicFakeEmbedding

from sqlagent.retrieval import (
    EmbeddingRetriever,
    SchemaRetriever,
    TfidfRetriever,
    build_retriever,
    load_table_docs,
)

DOCS = load_table_docs(ROOT / "docs" / "tables")


def test_loads_one_doc_per_table():
    assert {d.name for d in DOCS} == {
        "customers",
        "products",
        "orders",
        "order_items",
        "returns",
        "web_events",
    }
    orders = next(d for d in DOCS if d.name == "orders")
    assert orders.related == ["customers", "order_items"]


def test_tfidf_ranks_relevant_table_first():
    retriever = SchemaRetriever(DOCS, TfidfRetriever(DOCS), top_k=2)
    assert retriever.retrieve("how many customers signed up per country")[0].name == "customers"
    assert (
        retriever.retrieve("conversion funnel from add_to_cart to purchase by device")[0].name
        == "web_events"
    )
    assert retriever.retrieve("most common return reasons")[0].name == "returns"


def test_join_neighbours_are_added_but_bounded():
    retriever = SchemaRetriever(DOCS, TfidfRetriever(DOCS), top_k=1)
    names = [d.name for d in retriever.retrieve("return reasons")]
    assert names[0] == "returns"
    assert "order_items" in names and len(names) <= 1 + 2


def test_embedding_backend_returns_every_doc_ranked():
    backend = EmbeddingRetriever(DOCS, DeterministicFakeEmbedding(size=32))
    ranked = backend.scores("anything")
    assert len(ranked) == len(DOCS)
    assert SchemaRetriever(DOCS, backend, top_k=2).retrieve("anything")


def test_build_retriever_with_injected_embeddings():
    settings = make_settings(retrieval_backend="embeddings")
    retriever = build_retriever(settings, embeddings=DeterministicFakeEmbedding(size=16))
    assert retriever.retrieve("revenue")
