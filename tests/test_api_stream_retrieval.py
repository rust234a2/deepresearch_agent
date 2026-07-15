from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore
from deepresearch_agent.rag.retriever import ScopeHit


def _client(db, tmp, **kw):
    kw.setdefault("enable_scope", False)
    kw.setdefault("enable_graph", False)
    app = create_app(
        database_path=db, memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp), **kw,
    )
    return TestClient(app)


def _fake_polisher(report_type, report):
    yield "【LLM呈现】"
    yield report.get("supplier_name") or report.get("query", "")


def _brief_polisher(report_type, report):
    yield "【简短呈现】"


def test_stream_uses_polisher_without_forced_conclusion_banner(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=_fake_polisher)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body
    assert "【LLM呈现】" in body           # 走了 LLM
    reassembled = _reassemble(body)
    assert "结论：证据不足" not in reassembled


def test_stream_does_not_append_recommendation_when_polisher_omits_it(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=_brief_polisher)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert _reassemble(body) == "【简短呈现】"


def test_stream_falls_back_without_polisher(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=None)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: report_start" in body and "event: complete" in body
    assert "【LLM呈现】" not in body         # 未走 LLM，走确定性兜底
    assert "结论：证据不足" not in _reassemble(body)


def test_stream_polisher_exception_falls_back(company_database_path, tmp_path):
    def _boom(report_type, report):
        raise RuntimeError("llm down")
        yield  # pragma: no cover
    client = _client(company_database_path, tmp_path, polisher=_boom)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body        # 异常回退、不崩
    assert "结论：证据不足" not in _reassemble(body)


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


def _event_payload(body: str, event: str):
    import json
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"event: {event}":
            return json.loads(lines[i + 1].removeprefix("data:").strip())
    return None


def test_stream_emits_graph_subgraph_before_report(company_database_path, tmp_path, monkeypatch):
    from deepresearch_agent.agents import graph as graph_module
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext, SharedController

    def build_scope(database_path, index_path):
        return _ScopeRetriever()

    def build_graph(database_path, scope_retriever):
        def search(query):
            return HybridContext(
                query=query,
                seeds=[
                    SeedContext(code="91330000123456789X", name="示例科技股份有限公司",
                                score=0.95, controllers=[], neighbors=[]),
                    SeedContext(code="91330000123456780Y", name="样例精密股份有限公司",
                                score=0.80, controllers=[], neighbors=[]),
                ],
                shared_controllers=[SharedController(
                    node_id="person:张三", name="张三",
                    controlled_seeds=["91330000123456789X", "91330000123456780Y"],
                    via_person=True,
                )],
            )
        return search

    monkeypatch.setattr(graph_module, "_build_scope_retriever", build_scope)
    monkeypatch.setattr(graph_module, "_build_graph_searcher", build_graph)
    client = _client(company_database_path, tmp_path, polisher=None,
                     enable_scope=True, enable_graph=True)

    with client.stream("POST", "/session/turn/stream",
                       json={"question": "哪些做注塑的供应商互相关联", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())

    assert "event: graph_subgraph" in body
    assert body.index("event: graph_subgraph") < body.index("event: report_start")
    payload = _event_payload(body, "graph_subgraph")
    assert {n["id"] for n in payload["nodes"]} == {
        "query", "91330000123456789X", "91330000123456780Y", "person:张三",
    }
    hub = next(n for n in payload["nodes"] if n["kind"] == "query")
    assert hub["name"] == "哪些做注塑的供应商互相关联"


def test_stream_named_mode_has_no_graph_subgraph_event(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=None)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "graph_subgraph" not in body


def test_stream_scope_mode_has_no_graph_subgraph_event(company_database_path, tmp_path, monkeypatch):
    from deepresearch_agent.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "_build_scope_retriever",
                        lambda database_path, index_path: _ScopeRetriever())
    client = _client(company_database_path, tmp_path, polisher=None,
                     enable_scope=True, enable_graph=False)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "哪些企业能做注塑成型", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "graph_subgraph" not in body
    assert "event: report_start" in body
