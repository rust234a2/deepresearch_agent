from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.session import Session

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def test_memory_off_behaves_as_before(company_database_path):
    state = run_research(ENTITY, database_path=company_database_path)
    assert state.report is not None
    assert state.supplier_resolution.unified_social_credit_code == CODE
    assert state.preresolved is None


def test_coreference_resolves_pronoun_to_prior_entity(company_database_path):
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(FakeMemoryBackend())
    # 第一轮：解析到实体
    s1 = run_research(
        ENTITY, database_path=company_database_path, session=session, memory=memory, enable_memory=True
    )
    assert s1.supplier_resolution.unified_social_credit_code == CODE
    # 第二轮：指代 → 回退到上一轮实体
    s2 = run_research(
        "它的联系方式呢",
        database_path=company_database_path,
        session=session,
        memory=memory,
        enable_memory=True,
    )
    assert s2.supplier_resolution is not None
    assert s2.supplier_resolution.unified_social_credit_code == CODE
    assert s2.supplier_name == ENTITY


def test_remember_called_with_question_and_summary(company_database_path):
    backend = FakeMemoryBackend()
    session = Session(user_id="u", session_id="s")
    run_research(
        ENTITY,
        database_path=company_database_path,
        session=session,
        memory=MemoryService(backend),
        enable_memory=True,
    )
    stored = backend.store.get("u", [])
    assert stored and ENTITY in stored[0]  # 问题进了记忆


def test_recall_surfaced_in_report_open_questions(company_database_path):
    backend = FakeMemoryBackend()
    backend.store["u"] = ["你此前研究过示例科技股份有限公司"]
    session = Session(user_id="u", session_id="s")
    state = run_research(
        ENTITY,
        database_path=company_database_path,
        session=session,
        memory=MemoryService(backend),
        enable_memory=True,
    )
    assert any("历史记忆" in q for q in state.report.open_questions)


def test_no_coreference_without_prior_entity(company_database_path):
    session = Session(user_id="u", session_id="s")
    state = run_research(
        "它的联系方式呢",
        database_path=company_database_path,
        session=session,
        memory=MemoryService(FakeMemoryBackend()),
        enable_memory=True,
    )
    # 无历史实体 → 指代无回退 → not_found → 未解析报告
    assert state.supplier_resolution.status == "not_found"
