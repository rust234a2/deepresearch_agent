from __future__ import annotations

import csv
from pathlib import Path

from deepresearch_agent.company_data_cleaning import normalize_date, parse_capital
from deepresearch_agent.company_database import normalize_company_name
from deepresearch_agent.vendor_export import clean_cell, unquote


OUTPUT_COLUMNS = [
    "company_name",
    "normalized_company_name",
    "investee_name",
    "normalized_investee_name",
    "status",
    "investee_established_date",
    "holding_pct",
    "subscribed_capital_amount",
    "subscribed_capital_currency",
    "subscribed_capital_original",
    "final_beneficiary_pct",
    "region",
    "industry",
    "associated_product",
]


def _col(raw: list[str], index: int) -> str:
    return clean_cell(raw[index]) if len(raw) > index else ""


def clean_investment_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header_seen = False
    seen_keys: set[tuple[str, ...]] = set()
    for raw in raw_rows:
        cells = [unquote(cell) for cell in raw]
        if not header_seen:
            if cells and cells[0] == "企业名称":
                header_seen = True
            continue
        if len(cells) < 2:
            continue
        company_name = clean_cell(raw[0])
        investee_name = clean_cell(raw[1])
        if not company_name or not investee_name:
            continue
        amount, currency, original = parse_capital(_col(raw, 5))
        record = {
            "company_name": company_name,
            "normalized_company_name": normalize_company_name(company_name),
            "investee_name": investee_name,
            "normalized_investee_name": normalize_company_name(investee_name),
            "status": _col(raw, 2),
            "investee_established_date": normalize_date(_col(raw, 3)),
            "holding_pct": _col(raw, 4),
            "subscribed_capital_amount": amount,
            "subscribed_capital_currency": currency,
            "subscribed_capital_original": original,
            "final_beneficiary_pct": _col(raw, 6),
            "region": _col(raw, 7),
            "industry": _col(raw, 8),
            "associated_product": _col(raw, 9),
        }
        key = tuple(record[column] for column in OUTPUT_COLUMNS)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(record)
    return rows


def run_cleaning(input_path: str | Path, output_path: str | Path) -> dict[str, int]:
    input_path = Path(input_path)
    with input_path.open(encoding="gb18030", newline="") as handle:
        raw_rows = list(csv.reader(handle))

    rows = clean_investment_rows(raw_rows)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "edges": len(rows),
        "investors": len({row["normalized_company_name"] for row in rows}),
        "investees": len({row["normalized_investee_name"] for row in rows}),
        "active_edges": sum(1 for row in rows if row["status"] == "存续"),
    }
