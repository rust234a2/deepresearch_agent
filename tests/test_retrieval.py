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
