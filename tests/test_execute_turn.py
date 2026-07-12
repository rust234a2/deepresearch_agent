from pathlib import Path

from deepresearch_agent.agents.graph import build_graph, execute_turn
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.session import Session

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def _app(db_path):
    domain_pack = load_domain_pack(Path("domains") / "procurement" / "domain.yaml")
    return build_graph(domain_pack, CompanyRepository(db_path))


def test_execute_turn_coreference(company_database_path):
    app = _app(company_database_path)
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(FakeMemoryBackend())

    s1 = execute_turn(app, ENTITY, "procurement", session=session, memory=memory, enable_memory=True)
    assert s1.supplier_resolution.unified_social_credit_code == CODE

    s2 = execute_turn(
        app, "它的联系方式呢", "procurement", session=session, memory=memory, enable_memory=True
    )
    assert s2.supplier_resolution.unified_social_credit_code == CODE


def test_execute_turn_memory_off_is_plain(company_database_path):
    app = _app(company_database_path)
    state = execute_turn(app, ENTITY, "procurement")
    assert state.report is not None
    assert state.preresolved is None
