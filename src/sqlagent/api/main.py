from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..db import PostgresWarehouse
from ..graph import build_default_graph
from ..retrieval import load_table_docs
from ..service import AgentService, NoPendingApproval, QueryResponse


class QueryRequest(BaseModel):
    question: str = Field(
        min_length=3, max_length=1000, examples=["What was revenue by month in 2024?"]
    )


class ApprovalDecision(BaseModel):
    approved: bool


def get_service(app: FastAPI) -> AgentService:
    return app.state.service


def create_app(service: AgentService | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or AgentService(build_default_graph(settings), settings)
        yield

    app = FastAPI(
        title="Agentic Text-to-SQL Analytics Assistant",
        version="0.1.0",
        description="Ask business questions in plain English; get validated SQL, a chart and a summary.",
        lifespan=lifespan,
    )
    if service is not None:  # allow use without running the lifespan (e.g. in tests)
        app.state.service = service

    def auth(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and not secrets.compare_digest(x_api_key or "", settings.api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    def svc() -> AgentService:
        return app.state.service

    @app.get("/health")
    def health() -> dict:
        warehouse = PostgresWarehouse(settings.warehouse_dsn)
        return {"status": "ok" if warehouse.ping() else "degraded", "warehouse": warehouse.ping()}

    @app.get("/v1/tables", dependencies=[Depends(auth)])
    def tables() -> list[dict]:
        return [{"name": d.name, "related": d.related} for d in load_table_docs(settings.docs_dir)]

    @app.post("/v1/query", response_model=QueryResponse, dependencies=[Depends(auth)])
    def query(body: QueryRequest, service: AgentService = Depends(svc)) -> QueryResponse:
        """Run the agent. Returns ``awaiting_approval`` when the query is expensive."""
        try:
            return service.ask(body.question)
        except Exception as exc:  # LLM / network failures
            raise HTTPException(status_code=502, detail=f"Agent failed: {exc}") from exc

    @app.post(
        "/v1/query/{thread_id}/approval", response_model=QueryResponse, dependencies=[Depends(auth)]
    )
    def approval(
        thread_id: str, body: ApprovalDecision, service: AgentService = Depends(svc)
    ) -> QueryResponse:
        """Approve or reject a query that is waiting at the human-approval checkpoint."""
        try:
            return service.resume(thread_id, body.approved)
        except NoPendingApproval as exc:
            raise HTTPException(
                status_code=404, detail="No pending approval for this thread"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Agent failed: {exc}") from exc

    return app


def app_factory() -> FastAPI:
    """uvicorn entrypoint: ``uvicorn sqlagent.api.main:app_factory --factory``."""
    return create_app()
