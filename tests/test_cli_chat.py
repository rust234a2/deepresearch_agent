from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.cli import run_chat_loop
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.session import Session

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def test_chat_loop_multi_turn_coreference(company_database_path):
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(FakeMemoryBackend())
    lines = iter([ENTITY, "它的联系方式呢", "exit"])
    states = []

    def read_line():
        return next(lines, None)

    def run_turn(line, s, m):
        return run_research(
            line,
            database_path=company_database_path,
            session=s,
            memory=m,
            enable_memory=True,
        )

    run_chat_loop(session, memory, read_line, states.append, run_turn)

    assert len(states) == 2  # exit 不产出
    assert states[0].supplier_resolution.unified_social_credit_code == CODE
    # 第二轮靠会话指代解析到同一实体
    assert states[1].supplier_resolution.unified_social_credit_code == CODE


def test_chat_loop_stops_on_exit_and_none():
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(None)
    emitted = []
    for stopper in (["exit"], [None]):
        it = iter(stopper)
        run_chat_loop(
            session,
            memory,
            lambda: next(it, None),
            emitted.append,
            lambda line, s, m: emitted.append("RAN"),
        )
    assert emitted == []  # exit / None 立即停，未跑任何轮
