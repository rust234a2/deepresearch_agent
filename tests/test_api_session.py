from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def _client_with_store(db_path, store_dir):
    app = create_app(
        database_path=db_path,
        memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(store_dir),
        enable_scope=False,
        enable_graph=False,
    )
    return TestClient(app)


def _client(company_database_path, tmp_path):
    return _client_with_store(company_database_path, tmp_path)


def test_first_turn_returns_session_id(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r = client.post("/session/turn", json={"question": ENTITY, "user_id": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"]  # 服务端生成并回传
    assert body["report"]["supplier_name"] == ENTITY


def test_session_list_is_owned_and_uses_first_question_as_title(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    client.post("/session/turn", json={"question": ENTITY, "user_id": "alice"})
    client.post("/session/turn", json={"question": ENTITY, "user_id": "bob"})

    r = client.get("/sessions", params={"user_id": "alice"})

    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["title"] == ENTITY
    assert r.json()[0]["updated_at"]


def test_second_turn_coreference(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r1 = client.post("/session/turn", json={"question": ENTITY, "user_id": "alice"})
    sid = r1.json()["session_id"]
    r2 = client.post(
        "/session/turn",
        json={"question": "它的联系方式呢", "user_id": "alice", "session_id": sid},
    )
    assert r2.status_code == 200
    assert r2.json()["report"]["supplier_name"] == ENTITY  # 指代到同实体


def test_ownership_blocks_other_user(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    sid = client.post("/session/turn", json={"question": ENTITY, "user_id": "alice"}).json()[
        "session_id"
    ]
    # bob 拿 alice 的 session_id → 404
    r = client.post(
        "/session/turn", json={"question": "它的股东", "user_id": "bob", "session_id": sid}
    )
    assert r.status_code == 404
    # alice 的会话仍在、未被覆写
    ok = client.post(
        "/session/turn",
        json={"question": "它的联系方式呢", "user_id": "alice", "session_id": sid},
    )
    assert ok.json()["report"]["supplier_name"] == ENTITY


def test_invalid_session_id_400(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r = client.post(
        "/session/turn",
        json={"question": ENTITY, "user_id": "alice", "session_id": "../../etc/passwd"},
    )
    assert r.status_code == 400


def test_cross_request_persistence(company_database_path, tmp_path):
    # 两个独立 client 共享同一磁盘 store（模拟跨进程）
    c1 = _client_with_store(company_database_path, tmp_path)
    sid = c1.post("/session/turn", json={"question": ENTITY, "user_id": "alice"}).json()[
        "session_id"
    ]
    c2 = _client_with_store(company_database_path, tmp_path)
    r = c2.post(
        "/session/turn",
        json={"question": "它的联系方式呢", "user_id": "alice", "session_id": sid},
    )
    assert r.json()["report"]["supplier_name"] == ENTITY


def test_research_endpoint_unchanged(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r = client.post("/research", json={"question": ENTITY})
    assert r.status_code == 200
    assert r.json()["supplier_name"] == ENTITY  # 旧端点形状不变
