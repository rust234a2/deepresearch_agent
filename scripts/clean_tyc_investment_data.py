from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from deepresearch_agent.investment_data_cleaning import run_cleaning


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Clean Tianyancha outbound-investment export into an edge CSV.")
    parser.add_argument("--input", type=Path, required=True, help="Source Tianyancha 对外投资 .csv file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/procurement/processed/investments.csv"),
    )
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f"input file does not exist: {args.input}")

    summary = run_cleaning(args.input, args.output)
    for key, value in summary.items():
        print(f"{key}={value}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
