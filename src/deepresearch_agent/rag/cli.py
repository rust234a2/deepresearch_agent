from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from deepresearch_agent.rag.embedding import BgeEmbedder, Embedder
from deepresearch_agent.rag.retriever import ScopeHit, load_scope_retriever


def render_hits(query: str, hits: list[ScopeHit]) -> Table:
    table = Table(title=f"Scope search: {query}")
    table.add_column("Company")
    table.add_column("Section")
    table.add_column("Clause")
    table.add_column("Score")
    for hit in hits:
        table.add_row(hit.legal_name, hit.section_label or "", hit.text, f"{hit.score:.3f}")
    return table


def main(argv: list[str] | None = None, embedder: Embedder | None = None) -> None:
    parser = argparse.ArgumentParser(description="Semantic search over company business scope.")
    parser.add_argument("query", help="Capability description to search for.")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--database", default="data/procurement/derived/companies.sqlite3")
    parser.add_argument("--index", default="data/procurement/derived/scope_index.faiss")
    args = parser.parse_args(argv)

    used_embedder = embedder if embedder is not None else BgeEmbedder()
    retriever = load_scope_retriever(Path(args.database), Path(args.index), used_embedder)
    hits = retriever.search(args.query, args.k)
    Console().print(render_hits(args.query, hits))


if __name__ == "__main__":
    main()
