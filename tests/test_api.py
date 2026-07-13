from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app


def test_research_api_returns_source_backed_report(company_database_path):
    client = TestClient(create_app(company_database_path, enable_scope=False, enable_graph=False))

    response = client.post(
        "/research",
        json={"question": "核验示例科技股份有限公司"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["supplier_name"] == "示例科技股份有限公司"
    assert data["recommendation"] == "insufficient_evidence"
    assert data["evidence_table"]


def test_research_api_rejects_blank_question(company_database_path):
    client = TestClient(create_app(company_database_path, enable_scope=False, enable_graph=False))

    response = client.post("/research", json={"question": "   "})

    assert response.status_code == 422


def test_research_api_compiles_graph_once_across_requests(company_database_path, monkeypatch):
    from deepresearch_agent.agents import graph as graph_module

    calls = 0
    original_build = graph_module.build_graph

    def counting_build_graph(domain_pack, repository, **kwargs):
        nonlocal calls
        calls += 1
        return original_build(domain_pack, repository)

    monkeypatch.setattr(graph_module, "build_graph", counting_build_graph)

    client = TestClient(create_app(company_database_path, enable_scope=False, enable_graph=False))
    for _ in range(3):
        response = client.post("/research", json={"question": "核验示例科技股份有限公司"})
        assert response.status_code == 200

    assert calls == 1
