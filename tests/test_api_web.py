from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore

ENTITY = "示例科技股份有限公司"


def _client(company_database_path, tmp_path):
    app = create_app(
        database_path=company_database_path,
        memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp_path),
        enable_scope=False,
        enable_graph=False,
    )
    return TestClient(app)


def test_index_served_as_html(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "DeepResearch" in r.text


def test_static_css_served(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/style.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_static_js_served(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/app.js")
    assert r.status_code == 200


def test_web_includes_conversation_sidebar(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/")

    assert 'id="sidebar"' in r.text
    assert 'id="conversations"' in r.text
    assert 'id="newchat-side"' in r.text


def test_web_script_includes_session_deletion(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/app.js")

    assert 'method: "DELETE"' in r.text
    assert "deleteSession" in r.text


def test_research_endpoint_unchanged(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).post("/research", json={"question": ENTITY})
    assert r.status_code == 200
    assert r.json()["supplier_name"] == ENTITY


def test_web_includes_graph_panel(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/")
    assert 'id="graph-panel"' in r.text
    assert "线索级证据 · 须人工复核" in r.text
    assert 'id="graph-toggle"' in r.text
    assert "/static/graph.js" in r.text


def test_static_graph_js_served(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/graph.js")
    assert r.status_code == 200
    assert "window.GraphPanel" in r.text
    assert "认定" not in r.text  # 数据红线：面板代码不含认定式文案


def test_web_script_wires_graph_subgraph_event(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/app.js")
    assert 'event === "graph_subgraph"' in r.text
    assert "GraphPanel.render" in r.text
    assert "GraphPanel.clear" in r.text
