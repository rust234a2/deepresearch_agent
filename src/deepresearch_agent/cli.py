from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from deepresearch_agent.agents.graph import run_research


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a procurement DeepResearch supplier assessment.")
    parser.add_argument("question", help="Research question, including a known supplier name.")
    args = parser.parse_args(argv)

    state = run_research(args.question)
    if state.report is None:
        raise SystemExit("Research finished without a report.")

    console = Console()
    console.print(f"[bold]Supplier:[/bold] {state.report.supplier_name}")
    console.print(f"[bold]Recommendation:[/bold] {state.report.recommendation}")
    console.print(state.report.summary)

    table = Table(title="Evidence")
    table.add_column("Dimension")
    table.add_column("Claim")
    table.add_column("Source")
    for item in state.report.evidence_table:
        table.add_row(item.dimension, item.claim, item.citation.title)
    console.print(table)


if __name__ == "__main__":
    main()
