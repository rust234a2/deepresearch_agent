from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from deepresearch_agent.company_data_cleaning import run_cleaning


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean QCC company data into local CSV files.")
    parser.add_argument("--input", type=Path, required=True, help="Source QCC .xlsx file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/procurement/processed"),
    )
    args = parser.parse_args()
    if args.input.suffix.casefold() != ".xlsx":
        parser.error("--input must be an .xlsx file")
    if not args.input.is_file():
        parser.error(f"input file does not exist: {args.input}")

    summary = run_cleaning(args.input, args.output_dir)
    for key, value in summary.items():
        print(f"{key}={value}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
