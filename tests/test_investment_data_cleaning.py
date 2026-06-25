import csv

from deepresearch_agent.investment_data_cleaning import (
    OUTPUT_COLUMNS,
    clean_investment_rows,
    run_cleaning,
)


def _header():
    return [
        '="企业名称"', '="被投资企业名称"', '="状态"', '="成立日期"', '="持股比例"',
        '="认缴出资额"', '="最终受益股份"', '="所属地区"', '="所属行业"', '="关联产品/机构"',
    ]


def _row():
    return [
        '="泰尔重工股份有限公司"', '="泰尔智慧（上海）激光科技有限公司"', '="存续"', '="2021-11-24"',
        '="100%"', '="6500万元人民币"', '="100%"', '="上海市闵行区"', '="科学研究和技术服务业"',
        '="泰尔股份"',
    ]


def test_clean_investment_rows_parses_capital_date_and_dedupes():
    raw = [
        ["声明..."],
        [],
        _header() + [""],
        _row() + [""],
        _row() + [""],
        ['="泰尔重工股份有限公司"', "", '="存续"', "", "", "", "", "", "", "", ""],
    ]

    rows = clean_investment_rows(raw)

    assert len(rows) == 1
    row = rows[0]
    assert row["investee_name"] == "泰尔智慧（上海）激光科技有限公司"
    assert row["normalized_investee_name"] == "泰尔智慧(上海)激光科技有限公司"
    assert row["status"] == "存续"
    assert row["investee_established_date"] == "2021-11-24"
    assert row["holding_pct"] == "100%"
    assert row["subscribed_capital_amount"] == "65000000"
    assert row["subscribed_capital_currency"] == "CNY"
    assert row["industry"] == "科学研究和技术服务业"


def test_investment_run_cleaning_reads_gb18030_roundtrip(tmp_path):
    src = tmp_path / "raw.csv"
    with src.open("w", encoding="gb18030", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["声明..."])
        writer.writerow(_header())
        writer.writerow(_row())
    out = tmp_path / "investments.csv"

    summary = run_cleaning(src, out)

    assert summary == {"edges": 1, "investors": 1, "investees": 1, "active_edges": 1}
    with out.open(encoding="utf-8-sig", newline="") as handle:
        got = list(csv.DictReader(handle))
    assert list(got[0].keys()) == OUTPUT_COLUMNS
    assert got[0]["investee_name"] == "泰尔智慧（上海）激光科技有限公司"
    assert got[0]["subscribed_capital_amount"] == "65000000"
