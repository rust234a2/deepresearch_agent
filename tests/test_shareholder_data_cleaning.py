import csv

from deepresearch_agent.shareholder_data_cleaning import (
    OUTPUT_COLUMNS,
    clean_shareholder_rows,
    run_cleaning,
)


def _header():
    return [
        '="企业名称"', '="股东名称"', '="股东类型"', '="股份类型"', '="持股数（股）"',
        '="认缴出资额"', '="认缴出资日期"', '="间接持股比例"', '="首次持股日期"',
        '="关联产品/机构"', "",
    ]


def test_clean_shareholder_rows_parses_dedupes_and_drops_blank_names():
    raw = [
        ["查企业  上企查查 ", " 联系电话", " 声明..."],
        [],
        ['="股东信息"', ""],
        _header(),
        ['="万马科技股份有限公司"', '="张德生"', '="自然人股东"', '="流通A股"', "28,843,500",
         '="-"', '="-"', '="1.4726%"', '="-"', '="-"', ""],
        ['="万马科技股份有限公司"', '="某私募基金"', '="其他投资者"', '="流通A股"', "6,700,000",
         '="-"', '="-"', '="-"', '="-"', '="-"', ""],
        ['="万马科技股份有限公司"', '="张德生"', '="自然人股东"', '="流通A股"', "28,843,500",
         '="-"', '="-"', '="1.4726%"', '="-"', '="-"', ""],
        ['="万马科技股份有限公司"', "", '="自然人股东"', "", "", "", "", "", "", "", ""],
    ]

    rows = clean_shareholder_rows(raw)

    assert [r["shareholder_name"] for r in rows] == ["张德生", "某私募基金"]
    first = rows[0]
    assert first["company_name"] == "万马科技股份有限公司"
    assert first["normalized_company_name"] == "万马科技股份有限公司"
    assert first["shareholder_is_person"] == "true"
    assert first["shares_held"] == "28843500"
    assert first["indirect_holding_pct"] == "1.4726%"
    assert rows[1]["shareholder_is_person"] == "false"


def test_shareholder_run_cleaning_writes_csv_roundtrip(tmp_path):
    src = tmp_path / "raw.csv"
    with src.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["声明..."])
        writer.writerow([c for c in _header() if c])
        writer.writerow(['="示例公司"', '="李四"', '="自然人股东"', '="流通A股"', "1,000",
                         '="-"', '="-"', '="-"', '="-"', '="-"'])
    out = tmp_path / "shareholders.csv"

    summary = run_cleaning(src, out)

    assert summary == {
        "edges": 1, "companies": 1, "shareholders": 1,
        "person_edges": 1, "entity_edges": 0,
    }
    with out.open(encoding="utf-8-sig", newline="") as handle:
        got = list(csv.DictReader(handle))
    assert list(got[0].keys()) == OUTPUT_COLUMNS
    assert got[0]["shareholder_name"] == "李四"
    assert got[0]["shares_held"] == "1000"
