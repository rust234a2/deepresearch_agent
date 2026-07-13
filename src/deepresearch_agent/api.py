from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
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
)
from deepresearch_agent.state import SupplierReport


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
    report: SupplierReport


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
) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")
    repository = CompanyRepository(database_path)
    compiled_graphs: dict[str, object] = {}
    memory_service = memory if memory is not None else MemoryService(build_memory_backend())
    store = session_store if session_store is not None else JsonSessionStore(DEFAULT_SESSIONS_DIR)
    if polisher == "__default__":
        polisher = build_deepseek_polisher()

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
                graph_for(request.domain),
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

                store.save(session)
                report_type, report = _resolve_report(state)
                yield _sse("report_start", {
                    "report_type": report_type,
                    "title": report.get("supplier_name") or report.get("query", ""),
                    "recommendation": report["recommendation"],
                })
                yield _sse("message_delta", {"text": _conclusion_line(report)})
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


_RECOMMENDATION_TEXT = {
    "insufficient_evidence": "证据不足，不能据此作出采购批准或风险结论。",
    "conditional": "存在前提条件，须人工复核。",
    "approve": "通过。",
    "reject": "不通过。",
}


def _conclusion_line(report: dict) -> str:
    rec = _RECOMMENDATION_TEXT.get(report["recommendation"], report["recommendation"])
    return f"\n\n结论：{rec}"


def _report_message_chunks(report: dict, report_type: str):
    rec = _RECOMMENDATION_TEXT.get(report["recommendation"], report["recommendation"])
    if report_type in ("named", "unresolved"):
        sections = [f"{report['supplier_name']}\n\n结论：{rec}", report.get("summary", "")]
    elif report_type == "scope":
        head = f"经营范围语义检索：{report['query']}\n\n结论：{rec}"
        lines = [f"· {c['legal_name']}（{c['top_score']:.2f}）" for c in report.get("candidates", [])]
        sections = [head, report.get("summary", ""), "候选企业：\n" + "\n".join(lines) if lines else ""]
    else:  # graph
        head = f"股权关系检索：{report['query']}\n\n结论：{rec}"
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
