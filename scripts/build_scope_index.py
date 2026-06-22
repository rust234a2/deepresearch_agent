from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

import numpy as np

from deepresearch_agent.rag.embedding import BgeEmbedder, Embedder
from deepresearch_agent.rag.faiss_store import FaissVectorStore


def build_scope_index(
    database_path: str | Path,
    index_path: str | Path,
    embedder: Embedder,
    *,
    now: str | None = None,
) -> dict[str, int]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    index_path = Path(index_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT chunk_id, text FROM business_scope_chunks ORDER BY chunk_id"
        ).fetchall()
        ids = [row["chunk_id"] for row in rows]
        texts = [row["text"] for row in rows]
        vectors = (
            embedder.embed_documents(texts)
            if texts
            else np.zeros((0, embedder.dimension), dtype=np.float32)
        )
        with connection:
            for chunk_id, vector in zip(ids, vectors):
                connection.execute(
                    "UPDATE business_scope_chunks SET embedding = ? WHERE chunk_id = ?",
                    (np.asarray(vector, dtype=np.float32).tobytes(), chunk_id),
                )
            connection.execute("DELETE FROM scope_index_metadata")
            connection.execute(
                "INSERT INTO scope_index_metadata VALUES (?, ?, ?, ?, ?)",
                (embedder.model_name, embedder.dimension, 1, len(ids), timestamp),
            )
        store = FaissVectorStore(embedder.dimension)
        if ids:
            store.add(ids, vectors)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        store.save(index_path)
        return {"chunks": len(ids)}
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the FAISS scope index from SQLite.")
    parser.add_argument("--database", default="data/procurement/derived/companies.sqlite3")
    parser.add_argument("--index", default="data/procurement/derived/scope_index.faiss")
    args = parser.parse_args(argv)
    summary = build_scope_index(Path(args.database), Path(args.index), BgeEmbedder())
    print(f"chunks={summary['chunks']}")


if __name__ == "__main__":
    main()
