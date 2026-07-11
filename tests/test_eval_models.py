import pytest
from pydantic import ValidationError

from deepresearch_agent.eval.models import GoldenEntityCase, GoldenScopeCase


def test_entity_case_resolved_requires_code():
    case = GoldenEntityCase(
        case_id="c1", question="核验甲", expected_status="resolved", expected_code="X"
    )
    assert case.expected_code == "X"


def test_entity_case_not_found_needs_no_code():
    case = GoldenEntityCase(case_id="c2", question="核验无", expected_status="not_found")
    assert case.expected_code is None


def test_scope_case_holds_expected_codes():
    case = GoldenScopeCase(case_id="s1", query="注塑", expected_codes=["X", "Y"], k=5)
    assert case.expected_codes == ["X", "Y"] and case.k == 5


def test_entity_case_rejects_bad_status():
    with pytest.raises(ValidationError):
        GoldenEntityCase(case_id="c3", question="q", expected_status="weird")
