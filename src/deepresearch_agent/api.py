from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, StringConstraints

from deepresearch_agent.agents import graph as graph_module
from deepresearch_agent.agents.graph import DEFAULT_DATABASE_PATH, execute_turn, run_compiled
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.memory.config import build_memory_backend
from deepresearch_agent.memory.service import MemoryService
from deepresearch_agent.memory.session import Session
from deepresearch_agent.memory.store import (
    InvalidSessionIdError,
    JsonSessionStore,
    SessionOwnershipError,
)
from deepresearch_agent.state import SupplierReport


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

DEFAULT_SESSIONS_DIR = Path("data/procurement/sessions")


class ResearchRequest(BaseModel):
    question: Question
    domain: str = "procurement"


class SessionTurnRequest(BaseModel):
    question: Question
    user_id: Question
    domain: str = "procurement"
    session_id: str | None = None


class SessionTurnResponse(BaseModel):
    session_id: str
    report: SupplierReport


def create_app(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    memory: MemoryService | None = None,
    session_store: JsonSessionStore | None = None,
) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")
    repository = CompanyRepository(database_path)
    compiled_graphs: dict[str, object] = {}
    memory_service = memory if memory is not None else MemoryService(build_memory_backend())
    store = session_store if session_store is not None else JsonSessionStore(DEFAULT_SESSIONS_DIR)

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

    @application.post("/session/turn", response_model=SessionTurnResponse)
    def session_turn(request: SessionTurnRequest) -> SessionTurnResponse:
        user_id = request.user_id
        if request.session_id is None:
            session = Session(user_id=user_id, session_id=uuid.uuid4().hex)
        else:
            try:
                loaded = store.load(request.session_id, user_id)
            except SessionOwnershipError:
                raise HTTPException(status_code=404, detail="session not found")
            except InvalidSessionIdError:
                raise HTTPException(status_code=400, detail="invalid session_id")
            session = loaded or Session(user_id=user_id, session_id=request.session_id)

        state = execute_turn(
            graph_for(request.domain),
            request.question,
            request.domain,
            session=session,
            memory=memory_service,
            enable_memory=True,
        )
        store.save(session)
        if state.report is None:
            raise RuntimeError("session turn completed without a report")
        return SessionTurnResponse(session_id=session.session_id, report=state.report)

    return application


app = create_app()
