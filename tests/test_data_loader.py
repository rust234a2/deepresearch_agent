import pytest

from deepresearch_agent.data_loader import find_supplier_profile, load_supplier_profiles


def test_load_supplier_profiles_from_fixture():
    profiles = load_supplier_profiles()

    acme = profiles[0]
    assert acme.company.legal_name == "ACME Sensors"
    assert "艾克米传感器" in acme.company.aliases
    assert "country" not in acme.company.model_dump()
    assert acme.capability.products == ["industrial temperature sensor", "pressure sensor"]
    assert acme.capability.monthly_capacity_units == 120000
    assert acme.compliance.certifications == ["ISO 9001", "RoHS"]
    assert acme.compliance.sanctions_listed is False
    assert acme.compliance.risk_summary == (
        "No sanctions match in local fixture. Delivery capacity requires customer reference confirmation."
    )
    assert acme.financial.risk_summary is None


def test_find_supplier_profile_by_name_case_insensitive():
    profile = find_supplier_profile("northstar components")

    assert profile.company.legal_name == "Northstar Components"
    assert profile.compliance.sanctions_listed is True
    assert profile.compliance.listing_reason == "Matched local export restriction fixture."


def test_find_supplier_profile_by_alias():
    profile = find_supplier_profile("Northstar")

    assert profile.company.legal_name == "Northstar Components"


def test_find_supplier_profile_raises_for_unknown_supplier():
    with pytest.raises(ValueError, match="Unknown supplier"):
        find_supplier_profile("Missing Supplier")
