from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore


def _client(db, tmp, **kw):
    app = create_app(
        database_path=db, memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp), **kw,
    )
    return TestClient(app)


def _fake_polisher(report_type, report):
    yield "【LLM呈现】"
    yield report.get("supplier_name") or report.get("query", "")


def test_stream_uses_polisher_when_present(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=_fake_polisher)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body
    assert "【LLM呈现】" in body           # 走了 LLM
    assert "证据不足" in body               # 结论句后端硬发


def test_stream_falls_back_without_polisher(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=None)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: report_start" in body and "event: complete" in body
    assert "【LLM呈现】" not in body         # 未走 LLM，走确定性兜底


def test_stream_polisher_exception_falls_back(company_database_path, tmp_path):
    def _boom(report_type, report):
        raise RuntimeError("llm down")
        yield  # pragma: no cover
    client = _client(company_database_path, tmp_path, polisher=_boom)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body        # 异常回退、不崩
    assert "证据不足" in body                # 结论句仍在
