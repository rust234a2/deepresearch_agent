from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from deepresearch_agent.agents import graph as graph_module
from deepresearch_agent.agents.graph import (
    DEFAULT_DATABASE_PATH,
    execute_turn,
    iter_execute_turn,
    run_compiled,
)
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.llm.deepseek import build_deepseek_polisher
from deepresearch_agent.memory.config import build_memory_backend
from deepresearch_agent.memory.service import MemoryService
from deepresearch_agent.memory.session import Session
from deepresearch_agent.memory.store import (
    InvalidSessionIdError,
    JsonSessionStore,
    SessionOwnershipError,
    SessionSummary,
)
from deepresearch_agent.state import GraphSearchReport, ScopeSearchReport, SupplierReport


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

DEFAULT_SESSIONS_DIR = Path("data/procurement/sessions")

WEB_DIR = Path(__file__).parent / "web"


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
    report: SupplierReport | ScopeSearchReport | GraphSearchReport


class SessionSummaryResponse(BaseModel):
    session_id: str
    title: str
    updated_at: str


_NODE_PROGRESS = {
    "planner": "已识别问题与企业，正在制定核验计划…",
    "researcher": "正在读取本地工商与联系方式证据…",
    "critic": "正在检查已覆盖的研究维度…",
    "writer": "正在根据已取得的证据生成报告…",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    memory: MemoryService | None = None,
    session_store: JsonSessionStore | None = None,
    polisher: object = "__default__",
    index_path: str | Path = graph_module.DEFAULT_INDEX_PATH,
    enable_scope: bool = True,
    enable_graph: bool = True,
) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")
    repository = CompanyRepository(database_path)
    compiled_graphs: dict[tuple[str, bool, bool], object] = {}
    memory_service = memory if memory is not None else MemoryService(build_memory_backend())
    store = session_store if session_store is not None else JsonSessionStore(DEFAULT_SESSIONS_DIR)
    if polisher == "__default__":
        polisher = build_deepseek_polisher()

    logger = logging.getLogger("deepresearch.api")
    try:
        from deepresearch_agent.neo4j_backend import Neo4jBackend
        Neo4jBackend.from_env()
        logger.info("[graph] Neo4j backend: connected")
    except Exception:
        logger.info("[graph] Neo4j backend: unavailable (fallback to scope)")

    def graph_for(domain: str, *, enable_retrieval: bool = False) -> object:
        scope_active = enable_retrieval and enable_scope
        graph_active = enable_retrieval and enable_graph
        cache_key = (domain, scope_active, graph_active)
        if cache_key not in compiled_graphs:
            domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
            scope_retriever = (
                graph_module._build_scope_retriever(database_path, index_path)
                if (scope_active or graph_active)
                else None
            )
            graph_searcher = (
                graph_module._build_graph_searcher(database_path, scope_retriever)
                if graph_active
                else None
            )
            compiled_graphs[cache_key] = graph_module.build_graph(
                domain_pack,
                repository,
                scope_retriever=scope_retriever,
                graph_searcher=graph_searcher,
                llm=graph_module._build_llm() if enable_retrieval else None,
                scope_enabled=scope_active,
                graph_enabled=graph_active,
            )
        return compiled_graphs[cache_key]

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
            graph_for(request.domain, enable_retrieval=True),
            request.question,
            request.domain,
            session=session,
            memory=memory_service,
            enable_memory=True,
        )
        if session.title is None:
            session.title = request.question
        store.save(session)
        _, report = _resolve_report(state)
        return SessionTurnResponse(session_id=session.session_id, report=report)

    @application.post("/session/turn/stream")
    def session_turn_stream(request: SessionTurnRequest) -> StreamingResponse:
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

        def events():
            yield _sse("session", {"session_id": session.session_id})
            yield _sse("progress", {"stage": "context", "message": "正在准备本轮对话上下文…"})
            for node_name, state in iter_execute_turn(
                graph_for(request.domain, enable_retrieval=True),
                request.question,
                request.domain,
                session=session,
                memory=memory_service,
                enable_memory=True,
            ):
                if node_name != "complete":
                    yield _sse("progress", {
                        "stage": node_name,
                        "message": _NODE_PROGRESS.get(node_name, "正在处理…"),
                    })
                    continue

                if session.title is None:
                    session.title = request.question
                store.save(session)
                report_type, report = _resolve_report(state)
                yield _sse("report_start", {
                    "report_type": report_type,
                    "title": report.get("supplier_name") or report.get("query", ""),
                    "recommendation": report["recommendation"],
                })
                used_llm = False
                if polisher is not None:
                    try:
                        for tok in polisher(report_type, report):
                            used_llm = True
                            yield _sse("message_delta", {"text": tok})
                    except Exception:
                        used_llm = False
                if not used_llm:
                    for text in _report_message_chunks(report, report_type):
                        yield _sse("message_delta", {"text": text})
                yield _sse("complete", {"session_id": session.session_id})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.get("/sessions", response_model=list[SessionSummaryResponse])
    def list_sessions(user_id: Question) -> list[SessionSummary]:
        return store.list_for_user(user_id)

    @application.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_session(session_id: str, user_id: Question) -> Response:
        try:
            deleted = store.delete(session_id, user_id)
        except SessionOwnershipError:
            raise HTTPException(status_code=404, detail="session not found")
        except InvalidSessionIdError:
            raise HTTPException(status_code=400, detail="invalid session_id")
        if not deleted:
            raise HTTPException(status_code=404, detail="session not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    return application


def _text_chunks(text: str, size: int = 18):
    """Split report prose into small SSE deltas for a chat-like reveal."""
    for start in range(0, len(text), size):
        yield text[start : start + size]


def _resolve_report(state) -> tuple[str, dict]:
    mode = state.retrieval_mode or "named"
    report = {"scope": state.scope_report, "graph": state.graph_report}.get(mode) or state.report
    if report is None:
        raise RuntimeError("turn completed without any report")
    return mode, report.model_dump(mode="json")


def _report_message_chunks(report: dict, report_type: str):
    if report_type in ("named", "unresolved"):
        sections = [report["supplier_name"], report.get("summary", "")]
    elif report_type == "scope":
        head = f"经营范围语义检索：{report['query']}"
        lines = [f"· {c['legal_name']}（{c['top_score']:.2f}）" for c in report.get("candidates", [])]
        sections = [head, report.get("summary", ""), "候选企业：\n" + "\n".join(lines) if lines else ""]
    else:  # graph
        head = f"股权关系检索：{report['query']}"
        cand = [f"· {c['legal_name']}｜最终控制人：{'、'.join(c.get('ultimate_controllers') or []) or '—'}"
                for c in report.get("candidates", [])]
        clue = [f"· {s['controller_name']} → {'、'.join(s.get('controlled_companies') or [])}（{s['note']}）"
                for s in report.get("shared_controllers", [])]
        sections = [
            head, report.get("summary", ""),
            "候选企业：\n" + "\n".join(cand) if cand else "",
            "围标线索（线索级·须人工复核）：\n" + "\n".join(clue) if clue else "",
        ]
    for section in sections:
        if section:
            yield from _text_chunks(f"\n\n{section}")


app = create_app()
