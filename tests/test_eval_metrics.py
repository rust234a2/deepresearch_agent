from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.eval.metrics import entity_resolution_metrics, scope_recall_metrics
from deepresearch_agent.eval.models import GoldenEntityCase, GoldenScopeCase


def _case(cid, status, code=None):
    return GoldenEntityCase(case_id=cid, question="q", expected_status=status, expected_code=code)


def test_entity_metrics_all_correct():
    cases = [_case("a", "resolved", "X"), _case("b", "not_found")]
    resolutions = [
        CompanyResolution(status="resolved", unified_social_credit_code="X"),
        CompanyResolution(status="not_found"),
    ]
    m = entity_resolution_metrics(cases, resolutions)
    assert m.total == 2 and m.accuracy == 1.0
    assert m.resolved_precision == 1.0 and m.resolved_recall == 1.0


def test_entity_metrics_wrong_code_and_false_resolve():
    cases = [_case("a", "resolved", "X"), _case("b", "not_found")]
    resolutions = [
        CompanyResolution(status="resolved", unified_social_credit_code="Y"),  # 错 code
        CompanyResolution(status="resolved", unified_social_credit_code="Z"),  # 假阳性 resolve
    ]
    m = entity_resolution_metrics(cases, resolutions)
    assert m.accuracy == 0.0
    assert m.resolved_precision == 0.0            # 预测 2 个 resolved，0 个对
    assert m.resolved_recall == 0.0               # 期望 1 个 resolved，0 个对


def test_scope_metrics_partial_and_zero():
    cases = [
        GoldenScopeCase(case_id="s1", query="q", expected_codes=["A", "B"]),
        GoldenScopeCase(case_id="s2", query="q", expected_codes=["C"]),
    ]
    retrieved = [{"A", "Z"}, set()]  # s1 命中 A（recall .5, precision .5）；s2 全丢
    m = scope_recall_metrics(cases, retrieved)
    assert m.total == 2
    assert m.mean_recall_at_k == 0.25             # (0.5 + 0.0) / 2
    assert m.mean_precision_at_k == 0.25          # (0.5 + 0.0) / 2
