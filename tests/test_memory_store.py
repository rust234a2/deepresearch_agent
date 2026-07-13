import pytest

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.memory.session import Session
from deepresearch_agent.memory.store import (
    InvalidSessionIdError,
    JsonSessionStore,
    SessionOwnershipError,
)


def _resolved(name: str, code: str) -> CompanyResolution:
    return CompanyResolution(
        status="resolved", legal_name=name, unified_social_credit_code=code, match_type="legal_name"
    )


def _session_with(user_id, session_id, *entities):
    s = Session(user_id=user_id, session_id=session_id)
    for e in entities:
        s.note_entity(e)
    return s


def test_save_load_round_trip_preserves_recent_entities(tmp_path):
    store = JsonSessionStore(tmp_path)
    s = Session(user_id="alice", session_id="sess-1")
    s.note_entity(_resolved("甲公司", "C1"))
    s.note_entity(_resolved("乙公司", "C2"))
    store.save(s)

    loaded = store.load("sess-1", "alice")
    assert loaded is not None
    assert loaded.user_id == "alice"
    assert loaded.session_id == "sess-1"
    assert [r.unified_social_credit_code for r in loaded.recent_entities] == ["C1", "C2"]
    # 载入后仍是最近实体在末尾，指代可用
    assert loaded.resolve_anaphora("它的联系方式呢").unified_social_credit_code == "C2"


def test_load_missing_returns_none(tmp_path):
    assert JsonSessionStore(tmp_path).load("nope", "alice") is None


def test_load_wrong_owner_raises_and_does_not_overwrite(tmp_path):
    store = JsonSessionStore(tmp_path)
    a = Session(user_id="alice", session_id="sess-1")
    a.note_entity(_resolved("甲公司", "C1"))
    store.save(a)
    with pytest.raises(SessionOwnershipError):
        store.load("sess-1", "bob")
    # alice 的会话未被动过
    still = store.load("sess-1", "alice")
    assert [r.unified_social_credit_code for r in still.recent_entities] == ["C1"]


def test_invalid_session_id_rejected_on_load_and_save(tmp_path):
    store = JsonSessionStore(tmp_path)
    with pytest.raises(InvalidSessionIdError):
        store.load("../../etc/passwd", "alice")
    with pytest.raises(InvalidSessionIdError):
        store.save(Session(user_id="alice", session_id="a/b"))


def test_save_is_atomic_and_file_readable(tmp_path):
    store = JsonSessionStore(tmp_path)
    store.save(Session(user_id="alice", session_id="sess-1"))
    # 目标文件存在、无残留临时文件
    files = sorted(p.name for p in tmp_path.iterdir())
    assert "sess-1.json" in files
    assert all(not f.endswith(".tmp") for f in files)


def test_cross_process_persistence_new_store_instance(tmp_path):
    JsonSessionStore(tmp_path).save(
        _session_with("alice", "sess-1", _resolved("甲公司", "C1"))
    )
    # 另一个 store 实例（模拟另一进程）能读回
    loaded = JsonSessionStore(tmp_path).load("sess-1", "alice")
    assert [r.unified_social_credit_code for r in loaded.recent_entities] == ["C1"]


def test_list_for_user_returns_only_owned_sessions_in_recent_order(tmp_path):
    store = JsonSessionStore(tmp_path)
    store.save(Session(user_id="alice", session_id="older", title="较早的核验"))
    store.save(Session(user_id="bob", session_id="hidden", title="不应泄露"))
    store.save(Session(user_id="alice", session_id="newer", title="最新的核验"))

    summaries = store.list_for_user("alice")

    assert [(item.session_id, item.title) for item in summaries] == [
        ("newer", "最新的核验"),
        ("older", "较早的核验"),
    ]
    assert all(item.updated_at for item in summaries)
