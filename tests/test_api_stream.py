from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore


def test_stream_turn_emits_progress_and_incremental_report(company_database_path, tmp_path):
    app = create_app(
        database_path=company_database_path,
        memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp_path),
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/session/turn/stream",
        json={"question": "示例科技股份有限公司", "user_id": "alice"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: session" in body
    assert "event: progress" in body
    assert "event: report_start" in body
    assert "event: summary_delta" in body
    assert "event: evidence" in body
    assert "event: complete" in body
