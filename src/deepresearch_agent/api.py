from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI
from pydantic import BaseModel, StringConstraints

from deepresearch_agent.agents.graph import DEFAULT_DATABASE_PATH, run_research
from deepresearch_agent.state import SupplierReport


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ResearchRequest(BaseModel):
    question: Question
    domain: str = "procurement"


def create_app(database_path: str | Path = DEFAULT_DATABASE_PATH) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")

    @application.post("/research", response_model=SupplierReport)
    def research(request: ResearchRequest) -> SupplierReport:
        state = run_research(
            request.question,
            domain=request.domain,
            database_path=database_path,
        )
        if state.report is None:
            raise RuntimeError("research graph completed without a report")
        return state.report

    return application


app = create_app()
