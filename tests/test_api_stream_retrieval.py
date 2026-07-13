from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.rag.retriever import ScopeHit
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore


def _client(db, tmp, **kw):
    kw.setdefault("enable_scope", False)
    kw.setdefault("enable_graph", False)
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


class _ScopeRetriever:
    def search(self, query, k):
        return [
            ScopeHit(
                unified_social_credit_code="91330000123456789X",
                legal_name="示例科技股份有限公司",
                section_label="一般项目",
                text="注塑成型",
                score=0.95,
            )
        ]


def test_web_session_injects_scope_retriever_for_capability_query(
    company_database_path, tmp_path, monkeypatch
):
    from deepresearch_agent.agents import graph as graph_module

    calls = {"scope": 0, "graph": 0}

    def build_scope(database_path, index_path):
        calls["scope"] += 1
        return _ScopeRetriever()

    def build_graph(database_path, scope_retriever):
        calls["graph"] += 1
        return None

    monkeypatch.setattr(graph_module, "_build_scope_retriever", build_scope)
    monkeypatch.setattr(graph_module, "_build_graph_searcher", build_graph)
    client = _client(
        company_database_path,
        tmp_path,
        polisher=None,
        enable_scope=True,
        enable_graph=True,
    )

    response = client.post(
        "/session/turn", json={"question": "哪些企业能做注塑成型", "user_id": "alice"}
    )

    assert response.status_code == 200
    assert response.json()["report"]["query"] == "哪些企业能做注塑成型"
    assert response.json()["report"]["candidates"][0]["legal_name"] == "示例科技股份有限公司"
    assert calls == {"scope": 1, "graph": 1}


def test_web_session_injects_graph_searcher_for_relationship_query(
    company_database_path, tmp_path, monkeypatch
):
    from deepresearch_agent.agents import graph as graph_module
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext

    def build_scope(database_path, index_path):
        return _ScopeRetriever()

    def build_graph(database_path, scope_retriever):
        def search(query):
            return HybridContext(
                query=query,
                seeds=[
                    SeedContext(
                        code="X",
                        name="示例科技股份有限公司",
                        score=0.95,
                        controllers=[],
                        neighbors=[],
                    )
                ],
                shared_controllers=[],
            )

        return search

    monkeypatch.setattr(graph_module, "_build_scope_retriever", build_scope)
    monkeypatch.setattr(graph_module, "_build_graph_searcher", build_graph)
    client = _client(
        company_database_path,
        tmp_path,
        polisher=None,
        enable_scope=True,
        enable_graph=True,
    )

    response = client.post(
        "/session/turn", json={"question": "哪些做注塑的供应商互相关联", "user_id": "alice"}
    )

    assert response.status_code == 200
    assert response.json()["report"]["query"] == "哪些做注塑的供应商互相关联"
    assert response.json()["report"]["candidates"][0]["legal_name"] == "示例科技股份有限公司"


def test_research_endpoint_does_not_build_web_retrievers(company_database_path, tmp_path, monkeypatch):
    from deepresearch_agent.agents import graph as graph_module

    def unexpected(*args, **kwargs):
        raise AssertionError("/research must not build web retrievers")

    monkeypatch.setattr(graph_module, "_build_scope_retriever", unexpected)
    monkeypatch.setattr(graph_module, "_build_graph_searcher", unexpected)
    client = _client(
        company_database_path,
        tmp_path,
        polisher=None,
        enable_scope=True,
        enable_graph=True,
    )

    response = client.post("/research", json={"question": "核验示例科技股份有限公司"})

    assert response.status_code == 200


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
