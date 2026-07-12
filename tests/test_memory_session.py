from collections import deque

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.memory.session import (
    ANAPHORA_MARKERS,
    Session,
    contains_anaphora,
)


def _resolved(name: str, code: str) -> CompanyResolution:
    return CompanyResolution(
        status="resolved", legal_name=name, unified_social_credit_code=code, match_type="legal_name"
    )


def test_contains_anaphora_detects_markers():
    assert contains_anaphora("它的联系方式呢")
    assert contains_anaphora("该公司的股东")
    assert contains_anaphora("上述企业的经营范围")
    assert not contains_anaphora("核验万马科技股份有限公司")


def test_note_entity_only_keeps_resolved():
    s = Session(user_id="u", session_id="s")
    s.note_entity(_resolved("甲公司", "C1"))
    s.note_entity(CompanyResolution(status="not_found"))
    s.note_entity(CompanyResolution(status="ambiguous"))
    assert [r.unified_social_credit_code for r in s.recent_entities] == ["C1"]


def test_resolve_anaphora_returns_most_recent():
    s = Session(user_id="u", session_id="s")
    s.note_entity(_resolved("甲公司", "C1"))
    s.note_entity(_resolved("乙公司", "C2"))
    hit = s.resolve_anaphora("它的联系方式呢")
    assert hit is not None and hit.unified_social_credit_code == "C2"


def test_resolve_anaphora_none_without_marker_or_buffer():
    s = Session(user_id="u", session_id="s")
    assert s.resolve_anaphora("它的股东") is None  # 空缓冲
    s.note_entity(_resolved("甲公司", "C1"))
    assert s.resolve_anaphora("核验乙公司") is None  # 无指代标记


def test_recent_entities_capped_at_five():
    s = Session(user_id="u", session_id="s")
    for i in range(7):
        s.note_entity(_resolved(f"公司{i}", f"C{i}"))
    assert isinstance(s.recent_entities, deque)
    assert len(s.recent_entities) == 5
    assert s.recent_entities[-1].unified_social_credit_code == "C6"


def test_markers_include_common_forms():
    for m in ("它", "该公司", "上述"):
        assert m in ANAPHORA_MARKERS
