from deepresearch_agent.supplier_resolution import resolve_supplier


def test_resolve_supplier_by_legal_name_case_insensitive():
    result = resolve_supplier("Assess acme sensors for industrial sensor procurement")

    assert result.status == "resolved"
    assert result.supplier_name == "ACME Sensors"
    assert result.match_type == "legal_name"


def test_resolve_supplier_by_alias():
    result = resolve_supplier("评估艾克米传感器的交付能力")

    assert result.status == "resolved"
    assert result.supplier_name == "ACME Sensors"
    assert result.matched_text == "艾克米传感器"
    assert result.match_type == "alias"


def test_resolve_supplier_reports_ambiguous_question():
    result = resolve_supplier("Compare ACME with Northstar for this purchase")

    assert result.status == "ambiguous"
    assert result.supplier_name is None
    assert result.candidates == ["ACME Sensors", "Northstar Components"]


def test_resolve_supplier_reports_unknown_question():
    result = resolve_supplier("Assess Missing Supplier for this purchase")

    assert result.status == "not_found"
    assert result.supplier_name is None
    assert result.candidates == []
