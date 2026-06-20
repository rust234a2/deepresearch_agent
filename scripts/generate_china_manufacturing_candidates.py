from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from deepresearch_agent.candidate_generation import (
    INDUSTRIES,
    build_candidates,
    classify_candidate,
    parse_source_page,
    write_candidates_csv,
)


SOURCE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SOURCE_COLUMNS = (
    "SECUCODE,ORG_NAME,LISTING_STATE,INDUSTRYCSRC1,COUNTRY,"
    "MAIN_BUSINESS,BUSINESS_SCOPE"
)


def fetch_source_page(page_number: int, retries: int = 3) -> dict:
    query = urlencode(
        {
            "sortColumns": "SECURITY_CODE",
            "sortTypes": "1",
            "pageSize": "500",
            "pageNumber": str(page_number),
            "reportName": "RPT_HSF9_BASIC_ORGINFO",
            "columns": SOURCE_COLUMNS,
            "source": "WEB",
            "client": "WEB",
            "filter": '(LISTING_STATE="0")',
        }
    )
    request = Request(
        f"{SOURCE_URL}?{query}",
        headers={"User-Agent": "deepresearch-agent/0.1 supplier-candidate-generator"},
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(attempt)
    raise RuntimeError(f"Failed to fetch source page {page_number}") from last_error


def fetch_source_records() -> list[dict]:
    first_payload = fetch_source_page(1)
    first_records, pages = parse_source_page(first_payload)
    records = list(first_records)
    for page_number in range(2, pages + 1):
        payload = fetch_source_page(page_number)
        page_records, _ = parse_source_page(payload)
        records.extend(page_records)
        print(f"Fetched page {page_number}/{pages}", flush=True)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Chinese manufacturing supplier candidates.")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/procurement/candidates/china_manufacturing_supplier_names.csv"),
    )
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 5000:
        parser.error("--limit must be between 1 and 5000")

    records = fetch_source_records()
    classified = [record for record in records if classify_candidate(record) is not None]
    unique_classified = {
        " ".join(str(record["ORG_NAME"]).split()).casefold()
        for record in classified
    }
    candidates = build_candidates(records, limit=args.limit)
    covered_industries = {candidate.industry for candidate in candidates}
    missing_industries = set(INDUSTRIES) - covered_industries
    if missing_industries:
        raise RuntimeError(f"No candidates found for industries: {sorted(missing_industries)}")

    write_candidates_csv(candidates, args.output)
    print(f"Source records: {len(records)}")
    print(f"Classified records: {len(classified)}")
    print(f"Unique classified companies: {len(unique_classified)}")
    print(f"Written candidates: {len(candidates)}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
