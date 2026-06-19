from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI
from pydantic import BaseModel, StringConstraints

from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.state import SupplierReport


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ResearchRequest(BaseModel):
    question: Question
    domain: str = "procurement"


app = FastAPI(title="DeepResearch Agent", version="0.1.0")


@app.post("/research", response_model=SupplierReport)
def research(request: ResearchRequest) -> SupplierReport:
    state = run_research(request.question, domain=request.domain)
    if state.report is None:
        raise RuntimeError("research graph completed without a report")
    return state.report
