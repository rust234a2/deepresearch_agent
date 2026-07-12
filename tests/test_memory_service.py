from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService


def test_service_none_backend_degrades_to_noop():
    svc = MemoryService(None)
    assert svc.memory_available is False
    assert svc.recall("u", "任何") == []
    svc.remember("u", [{"role": "user", "content": "hi"}])  # 不抛


def test_service_recall_and_remember_with_fake_backend():
    svc = MemoryService(FakeMemoryBackend())
    assert svc.memory_available is True
    svc.remember(
        "u",
        [{"role": "user", "content": "查甲公司"}, {"role": "assistant", "content": "甲公司摘要"}],
    )
    got = svc.recall("u", "甲")
    assert any("甲公司" in line for line in got)


def test_recall_isolated_per_user():
    backend = FakeMemoryBackend()
    svc = MemoryService(backend)
    svc.remember("u1", [{"role": "user", "content": "u1记忆"}])
    assert svc.recall("u2", "任何") == []


def test_recall_respects_limit():
    svc = MemoryService(FakeMemoryBackend())
    for i in range(10):
        svc.remember("u", [{"role": "user", "content": f"记忆{i}"}])
    assert len(svc.recall("u", "记忆", limit=3)) == 3


def test_service_swallows_backend_errors():
    class Boom:
        def search(self, user_id, query, limit):
            raise RuntimeError("boom")

        def add(self, user_id, messages):
            raise RuntimeError("boom")

    svc = MemoryService(Boom())
    assert svc.recall("u", "x") == []  # 异常吞掉→空
    svc.remember("u", [{"role": "user", "content": "x"}])  # 不抛
