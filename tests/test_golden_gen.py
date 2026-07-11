import csv
from pathlib import Path

import pytest

from deepresearch_agent.company_database import build_company_database, normalize_company_name
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.golden_gen import category_counts, generate_entity_golden
from deepresearch_agent.eval.runner import run_entity_resolution

FIXTURES = Path(__file__).parent / "fixtures" / "procurement"


def _code(i: int) -> str:
    return f"91330000{i:010d}"  # 8 + 10 = 18 位，唯一


# C1 变成歧义源（被 C5 的 alias 撞名），故 C1 不进 resolved_legal。
# 干净法定名源：C2 C3 C4 C5；唯一 alias 源：C3 的 "伽马材料有限公司"。
_COMPANIES = [
    {"code": _code(1), "legal_name": "阿尔法精密机械有限公司", "aliases": ""},
    {"code": _code(2), "legal_name": "贝塔电子科技有限公司", "aliases": ""},
    {"code": _code(3), "legal_name": "伽马新材料有限公司", "aliases": "伽马材料有限公司"},
    {"code": _code(4), "legal_name": "德尔塔自动化设备有限公司", "aliases": ""},
    {"code": _code(5), "legal_name": "艾普西隆机床有限公司", "aliases": "阿尔法精密机械有限公司"},
]


@pytest.fixture
def golden_repo(tmp_path) -> CompanyRepository:
    src_lines = (FIXTURES / "companies.csv").read_text(encoding="utf-8-sig").splitlines()
    header = src_lines[0].split(",")
    template = next(csv.DictReader(src_lines))
    comp_path = tmp_path / "companies.csv"
    with comp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for company in _COMPANIES:
            row = dict(template)
            row["source_name"] = company["legal_name"]
            row["legal_name"] = company["legal_name"]
            row["unified_social_credit_code"] = company["code"]
            row["aliases"] = company["aliases"]
            writer.writerow(row)
    cont_path = tmp_path / "contacts.csv"
    with cont_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["unified_social_credit_code", "legal_name", "phones", "emails", "mailing_address"],
        )
        writer.writeheader()
        for company in _COMPANIES:
            writer.writerow(
                {
                    "unified_social_credit_code": company["code"],
                    "legal_name": company["legal_name"],
                    "phones": "",
                    "emails": "",
                    "mailing_address": "",
                }
            )
    db_path = tmp_path / "companies.sqlite3"
    build_company_database(comp_path, cont_path, db_path)
    return CompanyRepository(db_path)


def _generate(repo: CompanyRepository):
    return generate_entity_golden(
        repo.get_all_company_names(),
        repo.iter_aliases(),
        seed=1,
        n_legal=3,
        n_alias=1,
        n_not_found=2,
        ambiguous_cap=25,
    )


def test_category_counts_match_requested(golden_repo):
    cases = _generate(golden_repo)
    assert category_counts(cases) == {
        "resolved_legal": 3,
        "resolved_alias": 1,
        "ambiguous": 1,
        "not_found": 2,
    }


def test_resolved_legal_excludes_homonym(golden_repo):
    cases = _generate(golden_repo)
    legal = [c for c in cases if c.case_id.startswith("resolved_legal")]
    # C1 的法定名撞了 C5 的 alias，绝不能作为 resolved 题
    assert all(c.question != "阿尔法精密机械有限公司" for c in legal)
    # 每条 resolved 题的 expected_code 唯一且正确
    names = golden_repo.get_all_company_names()
    for c in legal:
        assert c.expected_status == "resolved"
        assert names[c.expected_code] == c.question


def test_resolved_alias_case(golden_repo):
    cases = _generate(golden_repo)
    alias = [c for c in cases if c.case_id.startswith("resolved_alias")]
    assert len(alias) == 1
    assert alias[0].question == "伽马材料有限公司"
    assert alias[0].expected_status == "resolved"
    assert alias[0].expected_code == _code(3)


def test_ambiguous_case_has_both_codes(golden_repo):
    cases = _generate(golden_repo)
    amb = [c for c in cases if c.case_id.startswith("ambiguous")]
    assert len(amb) == 1
    assert amb[0].question == "阿尔法精密机械有限公司"
    assert amb[0].expected_status == "ambiguous"
    assert amb[0].expected_candidate_codes == sorted([_code(1), _code(5)])


def test_not_found_questions_contain_no_db_name(golden_repo):
    cases = _generate(golden_repo)
    nf = [c for c in cases if c.case_id.startswith("not_found")]
    assert len(nf) == 2
    db_names = {normalize_company_name(n) for n in golden_repo.get_all_company_names().values()}
    for c in nf:
        assert c.expected_status == "not_found"
        nq = normalize_company_name(c.question)
        assert all(name not in nq for name in db_names)


def test_closed_loop_accuracy_is_one(golden_repo):
    # 生成器与 resolve_text 语义一致的端到端证明
    cases = _generate(golden_repo)
    metrics = run_entity_resolution(golden_repo, cases)
    assert metrics.accuracy == 1.0


def test_deterministic_same_seed(golden_repo):
    a = _generate(golden_repo)
    b = _generate(golden_repo)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_write_golden_writes_loadable_yaml_and_returns_counts_only(golden_repo, tmp_path):
    from deepresearch_agent.eval.golden_gen import write_golden
    from deepresearch_agent.eval.runner import load_entity_cases

    out = tmp_path / "entity_resolution.local.yaml"
    counts = write_golden(
        golden_repo, out, seed=1, n_legal=3, n_alias=1, n_not_found=2, ambiguous_cap=25
    )
    # 返回值只有整数条数，无企业名（红线：结构上保证只回数字）
    assert counts == {"resolved_legal": 3, "resolved_alias": 1, "ambiguous": 1, "not_found": 2}
    assert all(isinstance(v, int) for v in counts.values())
    # 产出的 yaml 能被评测 loader 正常读回
    cases = load_entity_cases(out)
    assert len(cases) == 7
    assert {c.expected_status for c in cases} == {"resolved", "ambiguous", "not_found"}
