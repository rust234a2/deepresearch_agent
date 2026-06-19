from fastapi.testclient import TestClient

from deepresearch_agent.api import app


def test_research_api_returns_report():
    client = TestClient(app)

    response = client.post(
        "/research",
        json={"question": "Assess ACME Sensors for industrial sensor procurement"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["supplier_name"] == "ACME Sensors"
    assert data["evidence_table"]


def test_research_api_rejects_blank_question():
    client = TestClient(app)

    response = client.post(
        "/research",
        json={"question": "   "},
    )

    assert response.status_code == 422
