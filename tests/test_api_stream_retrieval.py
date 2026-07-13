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


def _fake_polisher(report_type, report, conclusion=""):
    # 忠实 LLM：原样陈述给定结论一次
    yield "【LLM呈现】"
    yield conclusion
    yield report.get("supplier_name") or report.get("query", "")


def _softening_polisher(report_type, report, conclusion=""):
    # 违规 LLM：软化/漏掉结论（不含"证据不足"）
    yield "该企业一切正常，可以通过。"


def test_stream_uses_polisher_no_duplicate_conclusion(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=_fake_polisher)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body
    assert "【LLM呈现】" in body           # 走了 LLM
    # 纯 LLM 呈现：结论由 LLM 陈述一次，后端不再硬发 → 全文只出现一次
    reassembled = _reassemble(body)
    assert reassembled.count("证据不足") == 1


def test_stream_redline_net_appends_when_llm_softens(company_database_path, tmp_path):
    # LLM 软化了结论 → 后端兜底补发正确结论
    client = _client(company_database_path, tmp_path, polisher=_softening_polisher)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "证据不足" in _reassemble(body)   # 兜底补上了红线结论


def test_stream_falls_back_without_polisher(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=None)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: report_start" in body and "event: complete" in body
    assert "【LLM呈现】" not in body         # 未走 LLM，走确定性兜底
    assert "证据不足" in _reassemble(body)   # 兜底文本含结论


def test_stream_polisher_exception_falls_back(company_database_path, tmp_path):
    def _boom(report_type, report, conclusion=""):
        raise RuntimeError("llm down")
        yield  # pragma: no cover
    client = _client(company_database_path, tmp_path, polisher=_boom)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body        # 异常回退、不崩
    assert "证据不足" in _reassemble(body)   # 结论仍在（确定性兜底）


def _reassemble(sse_body: str) -> str:
    import json
    out = ""
    for line in sse_body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                d = json.loads(line[5:].strip())
            except Exception:
                continue
            if "text" in d:
                out += d["text"]
    return out
