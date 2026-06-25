from __future__ import annotations

import csv
from pathlib import Path

from deepresearch_agent.company_database import normalize_company_name
from deepresearch_agent.vendor_export import clean_cell, unquote


OUTPUT_COLUMNS = [
    "company_name",
    "normalized_company_name",
    "shareholder_name",
    "shareholder_type",
    "shareholder_is_person",
    "share_class",
    "shares_held",
    "indirect_holding_pct",
    "associated_product",
]


def _shares(value: str) -> str:
    cleaned = clean_cell(value).replace(",", "")
    return cleaned if cleaned.isdigit() else ""


def clean_shareholder_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header_seen = False
    seen_keys: set[tuple[str, ...]] = set()
    for raw in raw_rows:
        cells = [unquote(cell) for cell in raw]
        if not header_seen:
            if cells and cells[0] == "企业名称":
                header_seen = True
            continue
        if len(cells) < 5:
            continue
        company_name = clean_cell(raw[0])
        shareholder_name = clean_cell(raw[1])
        shareholder_type = clean_cell(raw[2])
        if not company_name or not shareholder_name:
            continue
        record = {
            "company_name": company_name,
            "normalized_company_name": normalize_company_name(company_name),
            "shareholder_name": shareholder_name,
            "shareholder_type": shareholder_type,
            "shareholder_is_person": "true" if shareholder_type == "自然人股东" else "false",
            "share_class": clean_cell(raw[3]) if len(raw) > 3 else "",
            "shares_held": _shares(raw[4]) if len(raw) > 4 else "",
            "indirect_holding_pct": clean_cell(raw[7]) if len(raw) > 7 else "",
            "associated_product": clean_cell(raw[9]) if len(raw) > 9 else "",
        }
        key = tuple(record[column] for column in OUTPUT_COLUMNS)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(record)
    return rows


def run_cleaning(input_path: str | Path, output_path: str | Path) -> dict[str, int]:
    input_path = Path(input_path)
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))

    rows = clean_shareholder_rows(raw_rows)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    persons = sum(1 for row in rows if row["shareholder_is_person"] == "true")
    return {
        "edges": len(rows),
        "companies": len({row["normalized_company_name"] for row in rows}),
        "shareholders": len({row["shareholder_name"] for row in rows}),
        "person_edges": persons,
        "entity_edges": len(rows) - persons,
    }
