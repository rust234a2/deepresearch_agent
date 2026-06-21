from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from deepresearch_agent.company_database import build_company_database


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the local SQLite company database.")
    parser.add_argument("--companies", default="data/procurement/processed/companies.csv")
    parser.add_argument("--contacts", default="data/procurement/processed/contacts.csv")
    parser.add_argument("--output", default="data/procurement/derived/companies.sqlite3")
    args = parser.parse_args(argv)
    summary = build_company_database(args.companies, args.contacts, args.output)
    print(f"companies={summary['companies']} contacts={summary['contacts']}")


if __name__ == "__main__":
    main()
