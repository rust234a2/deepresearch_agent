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


def test_perturbation_metrics_groups_by_type():
    from deepresearch_agent.eval.metrics import perturbation_metrics

    def _p(cid, ptype, code="X"):
        return GoldenEntityCase(
            case_id=cid,
            question="q",
            expected_status="resolved",
            expected_code=code,
            perturbation_type=ptype,
        )

    cases = [
        _p("drop_suffix_0", "drop_suffix"),
        _p("drop_suffix_1", "drop_suffix"),
        _p("transpose_0", "transpose"),
    ]
    resolutions = [
        CompanyResolution(status="resolved", unified_social_credit_code="X"),  # recovery
        CompanyResolution(status="resolved", unified_social_credit_code="Y"),  # wrong
        CompanyResolution(status="not_found"),                                  # miss
    ]
    m = perturbation_metrics(cases, resolutions)

    assert m.total == 3
    assert m.overall_recovery == 1 / 3
    by_type = {t.perturbation_type: t for t in m.per_type}
    assert by_type["drop_suffix"].n == 2
    assert by_type["drop_suffix"].recovery == 0.5
    assert by_type["drop_suffix"].wrong == 0.5
    assert by_type["drop_suffix"].miss == 0.0
    assert by_type["transpose"].n == 1
    assert by_type["transpose"].miss == 1.0
    # per_type 按扰动类型名排序，稳定输出
    assert [t.perturbation_type for t in m.per_type] == ["drop_suffix", "transpose"]


def test_scope_lexical_metrics_precision_recall_and_tp_count():
    from deepresearch_agent.eval.metrics import scope_lexical_metrics

    # q1: 召回 {A,Z}，词面 TP {A,B} → precision .5、recall .5、tp 2
    # q2: 召回 {C}，词面 TP {C}     → precision 1、recall 1、tp 1
    m = scope_lexical_metrics([{"A", "Z"}, {"C"}], [{"A", "B"}, {"C"}])
    assert m.total == 2
    assert m.mean_lexical_precision_at_k == 0.75      # (.5 + 1) / 2
    assert m.mean_lexical_recall_at_k == 0.75         # (.5 + 1) / 2
    assert m.mean_lexical_tp_count == 1.5             # (2 + 1) / 2


def test_scope_judged_metrics_gain_over_lexical():
    from deepresearch_agent.eval.metrics import scope_judged_metrics

    # 召回 {A,B}；词面 TP {A}（只 A 字面命中）；判官覆盖 {A,B}（B 是语义命中）
    m = scope_judged_metrics([{"A", "B"}], [{"A", "B"}], [{"A"}])
    assert m.mean_judged_precision_at_k == 1.0        # 2/2
    assert m.mean_noise_at_k == 0.0                   # 1 - 1
    assert m.mean_semantic_gain_at_k == 0.5           # judged 1.0 - lexical .5
