from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI
from pydantic import BaseModel, StringConstraints

from deepresearch_agent.agents import graph as graph_module
from deepresearch_agent.agents.graph import DEFAULT_DATABASE_PATH, run_compiled
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.state import SupplierReport


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ResearchRequest(BaseModel):
    question: Question
    domain: str = "procurement"


def create_app(database_path: str | Path = DEFAULT_DATABASE_PATH) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")
    repository = CompanyRepository(database_path)
    compiled_graphs: dict[str, object] = {}

    def graph_for(domain: str) -> object:
        if domain not in compiled_graphs:
            domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
            compiled_graphs[domain] = graph_module.build_graph(domain_pack, repository)
        return compiled_graphs[domain]

    @application.post("/research", response_model=SupplierReport)
    def research(request: ResearchRequest) -> SupplierReport:
        state = run_compiled(graph_for(request.domain), request.question, request.domain)
        if state.report is None:
            raise RuntimeError("research graph completed without a report")
        return state.report

    return application


app = create_app()
