from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "does",
    "evidence",
    "exist",
    "exists",
    "for",
    "is",
    "of",
    "or",
    "supplier",
    "the",
    "to",
    "what",
}


@dataclass(frozen=True)
class RetrievalResult:
    source_id: str
    title: str
    url: str
    snippet: str
    score: float


class LocalDocumentRetriever:
    def __init__(self, document_dir: str | Path) -> None:
        self.document_dir = Path(document_dir)
        self.documents = self._load_documents()

    def _load_documents(self) -> list[tuple[Path, str, str]]:
        docs: list[tuple[Path, str, str]] = []
        for path in sorted(self.document_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip()
            docs.append((path, title, text))
        return docs

    def search(
        self,
        query: str,
        limit: int = 5,
        supplier_name: str | None = None,
    ) -> list[RetrievalResult]:
        query_terms = self._terms(query)
        supplier_key = self._slug(supplier_name) if supplier_name else None
        if supplier_name:
            query_terms -= self._terms(supplier_name)
        if not query_terms:
            return []

        scored: list[RetrievalResult] = []
        for path, title, text in self.documents:
            if supplier_key and path.stem != supplier_key:
                continue
            text_terms = self._terms(text)
            overlap = query_terms.intersection(text_terms)
            if not overlap:
                continue
            score = len(overlap) / max(len(query_terms), 1)
            scored.append(
                RetrievalResult(
                    source_id=f"doc:{path.stem}",
                    title=title,
                    url=f"local://procurement/documents/{path.name}",
                    snippet=self._snippet(text, overlap),
                    score=score,
                )
            )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {
            term.casefold()
            for term in re.findall(r"[A-Za-z0-9]+", text)
            if term.casefold() not in _STOP_WORDS
        }

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")

    @staticmethod
    def _snippet(text: str, overlap: set[str]) -> str:
        for sentence in re.split(r"(?<=[.])\s+", text.replace("\n", " ")):
            sentence_terms = LocalDocumentRetriever._terms(sentence)
            if sentence_terms.intersection(overlap):
                return sentence[:280]
        return text.replace("\n", " ")[:280]
