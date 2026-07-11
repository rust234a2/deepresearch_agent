from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.state import GraphSearchReport, ScopeSearchReport, SupplierReport


def main(argv: list[str] | None = None) -> None:
    raw = sys.argv[1:] if argv is None else argv
    if raw and raw[0] == "eval":
        _eval_main(raw[1:])
        return
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
    parser.add_argument(
        "--graph",
        action="store_true",
        help="启用 GraphRAG 能力检索：候选 + 最终控制人 + 共享控制人（围标线索）。",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="启用本地 Phoenix 链路追踪（需本地 pip install arize-phoenix 并 phoenix serve）。",
    )
    args = parser.parse_args(argv)

    state = run_research(
        args.question,
        database_path=args.database,
        index_path=args.index,
        enable_scope=True,
        enable_graph=args.graph,
        enable_tracing=args.trace,
    )

    console = Console()
    if state.graph_report is not None:
        _print_graph_report(console, state.graph_report)
    elif state.scope_report is not None:
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


def _print_graph_report(console: Console, report: GraphSearchReport) -> None:
    console.print(f"[bold]Query:[/bold] {report.query}")
    console.print(f"[bold]Recommendation:[/bold] {report.recommendation}")
    console.print(report.summary)

    candidates = Table(title="Candidates")
    candidates.add_column("Company")
    candidates.add_column("Ultimate controllers")
    candidates.add_column("Score")
    for candidate in report.candidates:
        controllers = "；".join(candidate.ultimate_controllers)
        candidates.add_row(candidate.legal_name, controllers, f"{candidate.top_score:.3f}")
    console.print(candidates)

    shared = Table(title="Shared controllers (bid-rigging clues)")
    shared.add_column("Controller")
    shared.add_column("Controlled candidates")
    shared.add_column("Note")
    for finding in report.shared_controllers:
        shared.add_row(
            finding.controller_name,
            "、".join(finding.controlled_companies),
            finding.note,
        )
    console.print(shared)


def _eval_main(argv: list[str]) -> None:
    from deepresearch_agent.company_repository import CompanyRepository
    from deepresearch_agent.eval.runner import (
        load_entity_cases,
        load_scope_cases,
        run_entity_resolution,
        run_scope_recall,
    )

    parser = argparse.ArgumentParser(prog="cli eval", description="确定性评测（企业识别 / scope 召回）。")
    sub = parser.add_subparsers(dest="kind", required=True)

    p_entity = sub.add_parser("entity", help="企业识别 P/R")
    p_entity.add_argument("--database", required=True)
    p_entity.add_argument("--cases", required=True)

    p_scope = sub.add_parser("scope", help="scope 检索 recall@k")
    p_scope.add_argument("--database", required=True)
    p_scope.add_argument("--index", required=True)
    p_scope.add_argument("--cases", required=True)

    args = parser.parse_args(argv)
    console = Console()

    if args.kind == "entity":
        repository = CompanyRepository(args.database)
        m = run_entity_resolution(repository, load_entity_cases(args.cases))
        console.print("[bold]Eval: entity resolution (procurement)[/bold]")
        console.print(
            f"  cases={m.total}  accuracy={m.accuracy:.2f}  "
            f"resolved_precision={m.resolved_precision:.2f}  resolved_recall={m.resolved_recall:.2f}"
        )
    else:
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        retriever = load_scope_retriever(args.database, args.index, BgeEmbedder())
        m = run_scope_recall(retriever, load_scope_cases(args.cases))
        console.print("[bold]Eval: scope recall@k (procurement)[/bold]")
        console.print(
            f"  cases={m.total}  mean_recall_at_k={m.mean_recall_at_k:.2f}  "
            f"mean_precision_at_k={m.mean_precision_at_k:.2f}"
        )


if __name__ == "__main__":
    main()
