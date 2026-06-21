from deepresearch_agent.retrieval.local import LocalDocumentRetriever


def _document_dir(tmp_path):
    (tmp_path / "acme-sensors.md").write_text(
        "# ACME Sensors Supplier Note\nISO 9001. Monthly delivery capacity is documented.",
        encoding="utf-8",
    )
    (tmp_path / "northstar-components.md").write_text(
        "# Northstar Components Supplier Note\nAn export restriction is recorded.",
        encoding="utf-8",
    )
    return tmp_path


def test_retriever_returns_citation_ready_results(tmp_path):
    retriever = LocalDocumentRetriever(_document_dir(tmp_path))

    results = retriever.search("ACME Sensors ISO 9001 delivery capacity", limit=2)

    assert results
    assert results[0].source_id.startswith("doc:")
    assert "ACME" in results[0].title
    assert results[0].snippet


def test_retriever_ranks_matching_supplier_above_other_docs(tmp_path):
    retriever = LocalDocumentRetriever(_document_dir(tmp_path))

    results = retriever.search("Northstar export restriction", limit=2)

    assert results[0].title == "Northstar Components Supplier Note"


def test_retriever_scopes_results_to_supplier(tmp_path):
    retriever = LocalDocumentRetriever(_document_dir(tmp_path))

    results = retriever.search(
        "supplier delivery capacity",
        supplier_name="ACME Sensors",
        limit=5,
    )

    assert results
    assert {result.source_id for result in results} == {"doc:acme-sensors"}


def test_retriever_returns_no_cross_supplier_negative_news(tmp_path):
    retriever = LocalDocumentRetriever(_document_dir(tmp_path))

    results = retriever.search(
        "ACME Sensors negative news risk signals",
        supplier_name="ACME Sensors",
        limit=5,
    )

    assert results == []


def test_retriever_ignores_stop_word_only_query(tmp_path):
    retriever = LocalDocumentRetriever(_document_dir(tmp_path))

    results = retriever.search("what for or exists", limit=5)

    assert results == []
