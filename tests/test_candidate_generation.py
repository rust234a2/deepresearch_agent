import csv
from pathlib import Path

from deepresearch_agent.candidate_generation import (
    Candidate,
    build_candidates,
    classify_candidate,
    parse_source_page,
    select_balanced_candidates,
    write_candidates_csv,
)


def test_classify_candidate_maps_sensor_company():
    record = {
        "ORG_NAME": "示例传感器股份有限公司",
        "INDUSTRYCSRC1": "仪器仪表制造业",
        "MAIN_BUSINESS": "工业传感器研发生产",
    }

    assert classify_candidate(record) == "仪器仪表与传感器"


def test_classify_candidate_prefers_semiconductor_over_equipment():
    record = {
        "ORG_NAME": "示例半导体设备股份有限公司",
        "INDUSTRYCSRC1": "专用设备制造业",
        "MAIN_BUSINESS": "半导体刻蚀设备制造",
    }

    assert classify_candidate(record) == "半导体"


def test_classify_candidate_rejects_non_manufacturing_company():
    record = {
        "ORG_NAME": "示例银行股份有限公司",
        "INDUSTRYCSRC1": "货币金融服务",
        "MAIN_BUSINESS": "商业银行服务",
    }

    assert classify_candidate(record) is None


def test_classify_candidate_rejects_pharmacy_retailer():
    record = {
        "ORG_NAME": "示例药房股份有限公司",
        "INDUSTRYCSRC1": "零售业",
        "MAIN_BUSINESS": "医药零售连锁和医药配送业务",
        "BUSINESS_SCOPE": "医疗器械和保健用品销售",
    }

    assert classify_candidate(record) is None


def test_classify_candidate_keeps_vehicle_manufacturer_in_automotive():
    record = {
        "ORG_NAME": "示例商用车股份有限公司",
        "INDUSTRYCSRC1": "汽车制造业",
        "MAIN_BUSINESS": "商用车的研发、生产和销售",
        "BUSINESS_SCOPE": "汽车及仪器仪表的制造和销售",
    }

    assert classify_candidate(record) == "汽车零部件"


def test_classify_candidate_keeps_engineering_machinery_in_equipment():
    record = {
        "ORG_NAME": "示例重工股份有限公司",
        "INDUSTRYCSRC1": "专用设备制造业",
        "MAIN_BUSINESS": "工程机械的研发、制造、销售和服务",
        "BUSINESS_SCOPE": "机械设备及橡胶制品销售",
    }

    assert classify_candidate(record) == "机械设备"


def test_build_candidates_deduplicates_legal_names():
    records = [
        {
            "ORG_NAME": "示例电子股份有限公司",
            "INDUSTRYCSRC1": "计算机、通信和其他电子设备制造业",
            "MAIN_BUSINESS": "电子元件制造",
        },
        {
            "ORG_NAME": " 示例电子股份有限公司 ",
            "INDUSTRYCSRC1": "计算机、通信和其他电子设备制造业",
            "MAIN_BUSINESS": "电子元件制造",
        },
    ]

    candidates = build_candidates(records, limit=5000)

    assert candidates == [Candidate("示例电子股份有限公司", "电子元器件")]


def test_select_balanced_candidates_respects_limit_and_uses_multiple_industries():
    candidates = [Candidate(f"机械企业{i}", "机械设备") for i in range(10)]
    candidates += [Candidate(f"电子企业{i}", "电子元器件") for i in range(10)]

    selected = select_balanced_candidates(candidates, limit=6)

    assert len(selected) == 6
    assert {item.industry for item in selected} == {"机械设备", "电子元器件"}


def test_write_candidates_csv_uses_expected_columns(tmp_path):
    output = tmp_path / "candidates.csv"

    write_candidates_csv([Candidate("示例设备股份有限公司", "机械设备")], output)

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{"supplier_name": "示例设备股份有限公司", "industry": "机械设备"}]


def test_checked_in_candidate_csv_has_expected_header():
    candidate_path = (
        Path(__file__).parents[1]
        / "data"
        / "procurement"
        / "candidates"
        / "china_manufacturing_supplier_names.csv"
    )

    with candidate_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames

    assert fieldnames == ["supplier_name", "industry"]


def test_parse_source_page_keeps_only_active_china_mainland_listings():
    payload = {
        "result": {
            "pages": 1,
            "data": [
                {
                    "ORG_NAME": "示例设备股份有限公司",
                    "LISTING_STATE": "0",
                    "COUNTRY": "China 中国",
                    "SECUCODE": "000001.SZ",
                },
                {
                    "ORG_NAME": "退市设备股份有限公司",
                    "LISTING_STATE": "1",
                    "COUNTRY": "China 中国",
                    "SECUCODE": "000002.SZ",
                },
                {
                    "ORG_NAME": "境外设备股份有限公司",
                    "LISTING_STATE": "0",
                    "COUNTRY": "United States 美国",
                    "SECUCODE": "000003.SZ",
                },
                {
                    "ORG_NAME": "港股设备股份有限公司",
                    "LISTING_STATE": "0",
                    "COUNTRY": "China 中国",
                    "SECUCODE": "00004.HK",
                },
            ],
        }
    }

    records, pages = parse_source_page(payload)

    assert pages == 1
    assert [item["ORG_NAME"] for item in records] == ["示例设备股份有限公司"]
