from deepresearch_agent.tools.procurement import build_procurement_tool_registry


def test_supplier_profile_tool_returns_structured_result():
    registry = build_procurement_tool_registry()

    result = registry.run("extract_supplier_profile", {"supplier_name": "ACME Sensors"})

    assert result.name == "extract_supplier_profile"
    assert result.status == "ok"
    assert result.data["supplier_name"] == "ACME Sensors"
    assert result.permission_tier == "read_public"


def test_sanctions_tool_flags_known_risk_supplier():
    registry = build_procurement_tool_registry()

    result = registry.run("check_sanctions_or_blacklist", {"company_name": "Northstar Components"})

    assert result.status == "ok"
    assert result.data["listed"] is True
    assert "export restriction" in result.data["reason"].lower()


def test_unknown_tool_raises_key_error():
    registry = build_procurement_tool_registry()

    try:
        registry.run("missing_tool", {})
    except KeyError as exc:
        assert "missing_tool" in str(exc)
    else:
        raise AssertionError("missing tool should raise KeyError")
