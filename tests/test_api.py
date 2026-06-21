from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app


def test_research_api_returns_source_backed_report(company_database_path):
    client = TestClient(create_app(company_database_path))

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
    client = TestClient(create_app(company_database_path))

    response = client.post("/research", json={"question": "   "})

    assert response.status_code == 422
