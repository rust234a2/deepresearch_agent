from deepresearch_agent.api import _report_message_chunks, _resolve_report
from deepresearch_agent.state import (
    GraphSearchCandidate, GraphSearchReport, ResearchState,
    ScopeCandidate, ScopeSearchReport, SharedControllerFinding, SupplierReport,
)


def _named_state():
    s = ResearchState(question="核验甲", domain="procurement")
    s.retrieval_mode = "named"
    s.supplier_name = "甲公司"
    s.report = SupplierReport(
        supplier_name="甲公司", recommendation="insufficient_evidence",
        summary="已核验工商。", risks=[], evidence_table=[], open_questions=[],
    )
    return s


def _scope_state():
    s = ResearchState(question="哪些能做注塑", domain="procurement")
    s.retrieval_mode = "scope"
    s.scope_report = ScopeSearchReport(
        query="哪些能做注塑", summary="检索到 1 家候选。",
        candidates=[ScopeCandidate(unified_social_credit_code="C1", legal_name="乙公司", matched_clauses=[], top_score=0.8)],
        open_questions=[],
    )
    return s


def _graph_state():
    s = ResearchState(question="找股东有关联的供应商", domain="procurement")
    s.retrieval_mode = "graph"
    s.graph_report = GraphSearchReport(
        query="找股东有关联的供应商", summary="检索到 2 家候选。",
        candidates=[GraphSearchCandidate(unified_social_credit_code="C1", legal_name="丙公司", top_score=0.8, ultimate_controllers=["张三"])],
        shared_controllers=[SharedControllerFinding(controller_name="张三", controlled_companies=["丙公司", "丁公司"], via_person=False, note="经企业股权链推断", concentrated_industries=["木材加工"])],
        open_questions=[],
    )
    return s


def test_resolve_report_picks_by_mode():
    assert _resolve_report(_named_state())[0] == "named"
    assert _resolve_report(_scope_state())[0] == "scope"
    assert _resolve_report(_graph_state())[0] == "graph"
    assert _resolve_report(_scope_state())[1]["query"] == "哪些能做注塑"


def test_chunks_named_has_supplier_and_summary():
    _, report = _resolve_report(_named_state())
    text = "".join(_report_message_chunks(report, "named"))
    assert "甲公司" in text and "已核验工商" in text


def test_chunks_scope_lists_candidates():
    _, report = _resolve_report(_scope_state())
    text = "".join(_report_message_chunks(report, "scope"))
    assert "乙公司" in text and "候选" in text


def test_chunks_graph_lists_candidates_and_collusion():
    _, report = _resolve_report(_graph_state())
    text = "".join(_report_message_chunks(report, "graph"))
    assert "丙公司" in text
    assert "张三" in text
    assert "须人工复核" in text
