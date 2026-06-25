from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_models import RelatedPartyConfig
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.ownership_links import find_related_parties


FIXTURES = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"

A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _repository(tmp_path: Path) -> CompanyRepository:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
        shareholders_csv=FIXTURES / "shareholders.csv",
        investments_csv=FIXTURES / "investments.csv",
    )
    return CompanyRepository(database_path)


def test_find_related_parties_covers_all_relation_types_and_filters_noise(tmp_path):
    repository = _repository(tmp_path)

    parties = find_related_parties(repository, A_CODE)

    pairs = {(p.related_code, p.relation_type) for p in parties}
    assert pairs == {
        (B_CODE, "direct_shareholder"),
        (C_CODE, "direct_investee"),
        (B_CODE, "shared_corporate_shareholder"),
        (B_CODE, "shared_investee"),
        (C_CODE, "shared_person_shareholder"),
    }
    # 嘉实…证券投资基金 是噪声，不得制造任何关联
    assert all("证券投资基金" not in (p.via_node_name or "") for p in parties)

    person = next(p for p in parties if p.relation_type == "shared_person_shareholder")
    assert person.confidence == 0.2
    assert person.via_is_person is True
    assert person.shared_degree == 2
    assert "须人工复核" in person.reliability_note

    corporate = next(p for p in parties if p.relation_type == "shared_corporate_shareholder")
    assert corporate.confidence == 0.5
    assert corporate.via_node_name == "共同控股集团有限公司"


def test_find_related_parties_sorted_by_confidence_then_code(tmp_path):
    repository = _repository(tmp_path)

    parties = find_related_parties(repository, A_CODE)

    keys = [(p.confidence, p.related_code) for p in parties]
    assert keys == sorted(keys, key=lambda k: (-k[0], k[1]))
    assert parties[0].confidence == 0.9


def test_find_related_parties_degree_cap_filters_corporate_links(tmp_path):
    repository = _repository(tmp_path)

    parties = find_related_parties(repository, A_CODE, RelatedPartyConfig(corporate_degree_cap=1))

    # 度 2 的共同控股集团被 cap=1 过滤；自然人不受企业 cap 影响仍在
    assert not any(p.relation_type == "shared_corporate_shareholder" for p in parties)
    assert any(p.relation_type == "shared_person_shareholder" for p in parties)


def test_find_related_parties_empty_for_unknown_code(tmp_path):
    repository = _repository(tmp_path)

    assert find_related_parties(repository, "no-such-code") == []
