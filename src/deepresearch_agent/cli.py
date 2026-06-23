from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.state import ScopeSearchReport, SupplierReport


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a procurement DeepResearch supplier assessment.")
    parser.add_argument(
        "question",
        help="Research question: a known supplier name, or a capability to search for.",
    )
    parser.add_argument(
        "--database",
        default="data/procurement/derived/companies.sqlite3",
        help="Path to the generated SQLite company database.",
    )
    parser.add_argument(
        "--index",
        default="data/procurement/derived/scope_index.faiss",
        help="Path to the FAISS business-scope index (for capability searches).",
    )
    args = parser.parse_args(argv)

    state = run_research(
        args.question,
        database_path=args.database,
        index_path=args.index,
        enable_scope=True,
    )

    console = Console()
    if state.scope_report is not None:
        _print_scope_report(console, state.scope_report)
    elif state.report is not None:
        _print_supplier_report(console, state.report)
    else:
        raise SystemExit("Research finished without a report.")


def _print_supplier_report(console: Console, report: SupplierReport) -> None:
    console.print(f"[bold]Supplier:[/bold] {report.supplier_name}")
    console.print(f"[bold]Recommendation:[/bold] {report.recommendation}")
    console.print(report.summary)

    table = Table(title="Evidence")
    table.add_column("Dimension")
    table.add_column("Claim")
    table.add_column("Source")
    for item in report.evidence_table:
        table.add_row(item.dimension, item.claim, item.citation.title)
    console.print(table)


def _print_scope_report(console: Console, report: ScopeSearchReport) -> None:
    console.print(f"[bold]Query:[/bold] {report.query}")
    console.print(f"[bold]Recommendation:[/bold] {report.recommendation}")
    console.print(report.summary)

    table = Table(title="Candidates")
    table.add_column("Company")
    table.add_column("Matched clauses")
    table.add_column("Score")
    for candidate in report.candidates:
        clauses = "；".join(evidence.claim for evidence in candidate.matched_clauses)
        table.add_row(candidate.legal_name, clauses, f"{candidate.top_score:.3f}")
    console.print(table)


if __name__ == "__main__":
    main()
