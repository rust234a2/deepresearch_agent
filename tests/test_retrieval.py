from deepresearch_agent.retrieval.local import LocalDocumentRetriever


def test_retriever_returns_citation_ready_results():
    retriever = LocalDocumentRetriever("data/procurement/documents")

    results = retriever.search("ACME Sensors ISO 9001 delivery capacity", limit=2)

    assert results
    assert results[0].source_id.startswith("doc:")
    assert "ACME" in results[0].title
    assert results[0].snippet


def test_retriever_ranks_matching_supplier_above_other_docs():
    retriever = LocalDocumentRetriever("data/procurement/documents")

    results = retriever.search("Northstar export restriction", limit=2)

    assert results[0].title == "Northstar Components Supplier Note"


def test_retriever_scopes_results_to_supplier():
    retriever = LocalDocumentRetriever("data/procurement/documents")

    results = retriever.search(
        "supplier delivery capacity",
        supplier_name="ACME Sensors",
        limit=5,
    )

    assert results
    assert {result.source_id for result in results} == {"doc:acme-sensors"}


def test_retriever_returns_no_cross_supplier_negative_news():
    retriever = LocalDocumentRetriever("data/procurement/documents")

    results = retriever.search(
        "ACME Sensors negative news risk signals",
        supplier_name="ACME Sensors",
        limit=5,
    )

    assert results == []


def test_retriever_ignores_stop_word_only_query():
    retriever = LocalDocumentRetriever("data/procurement/documents")

    results = retriever.search("what for or exists", limit=5)

    assert results == []
