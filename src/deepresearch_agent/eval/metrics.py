from __future__ import annotations

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.eval.models import (
    EntityResolutionMetrics,
    GoldenEntityCase,
    GoldenScopeCase,
    ScopeRecallMetrics,
)


def entity_resolution_metrics(
    cases: list[GoldenEntityCase], resolutions: list[CompanyResolution]
) -> EntityResolutionMetrics:
    total = len(cases)
    correct = pred_resolved = exp_resolved = correct_resolved = 0
    for case, res in zip(cases, resolutions):
        status_match = res.status == case.expected_status
        if case.expected_status == "resolved":
            exp_resolved += 1
            case_correct = status_match and res.unified_social_credit_code == case.expected_code
        else:
            case_correct = status_match
        if res.status == "resolved":
            pred_resolved += 1
            if case.expected_status == "resolved" and res.unified_social_credit_code == case.expected_code:
                correct_resolved += 1
        if case_correct:
            correct += 1
    return EntityResolutionMetrics(
        total=total,
        accuracy=correct / total if total else 1.0,
        resolved_precision=correct_resolved / pred_resolved if pred_resolved else 1.0,
        resolved_recall=correct_resolved / exp_resolved if exp_resolved else 1.0,
    )


def scope_recall_metrics(
    cases: list[GoldenScopeCase], retrieved_per_case: list[set[str]]
) -> ScopeRecallMetrics:
    recalls: list[float] = []
    precisions: list[float] = []
    for case, retrieved in zip(cases, retrieved_per_case):
        expected = set(case.expected_codes)
        hit = expected & retrieved
        recalls.append(len(hit) / len(expected) if expected else 1.0)
        precisions.append(len(hit) / len(retrieved) if retrieved else 0.0)
    total = len(cases)
    return ScopeRecallMetrics(
        total=total,
        mean_recall_at_k=sum(recalls) / total if total else 1.0,
        mean_precision_at_k=sum(precisions) / total if total else 0.0,
    )
