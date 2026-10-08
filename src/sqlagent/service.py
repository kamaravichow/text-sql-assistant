from __future__ import annotations

import uuid
from typing import Any, Literal

from langgraph.types import Command
from pydantic import BaseModel

from .config import Settings

Status = Literal["completed", "failed", "rejected", "unanswerable", "awaiting_approval"]


class ApprovalRequest(BaseModel):
    sql: str
    estimated_cost: float
    estimated_rows: float | None = None
    threshold: float


class QueryResponse(BaseModel):
    thread_id: str
    status: Status
    question: str
    sql: str | None = None
    summary: str | None = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    row_count: int = 0
    truncated: bool = False
    chart: dict | None = None
    estimated_cost: float | None = None
    attempts: int = 0
    error: str | None = None
    tables: list[str] = []
    approval: ApprovalRequest | None = None
    steps: list[dict] = []


class NoPendingApproval(LookupError):
    """The thread does not exist or is not waiting for a decision."""


class AgentService:
    """Thin application layer over the compiled graph: runs, pauses and resumes threads."""

    def __init__(self, graph, settings: Settings):
        self.graph = graph
        self.settings = settings

    def _config(self, thread_id: str, question: str = "") -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "run_name": "text_to_sql_agent",
            "tags": ["text-to-sql"],
            "metadata": {"thread_id": thread_id, "question": question[:200]},
        }

    def ask(self, question: str) -> QueryResponse:
        thread_id = uuid.uuid4().hex
        config = self._config(thread_id, question)
        self.graph.invoke({"question": question, "steps": []}, config)
        return self._snapshot(thread_id, config)

    def resume(self, thread_id: str, approved: bool) -> QueryResponse:
        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.values or not self._pending(snapshot):
            raise NoPendingApproval(thread_id)
        self.graph.invoke(Command(resume={"approved": approved}), config)
        return self._snapshot(thread_id, config)

    @staticmethod
    def _pending(snapshot) -> dict | None:
        for task in snapshot.tasks:
            for interrupt in task.interrupts:
                return interrupt.value
        return None

    def _snapshot(self, thread_id: str, config: dict) -> QueryResponse:
        snapshot = self.graph.get_state(config)
        values = snapshot.values
        pending = self._pending(snapshot)
        response = QueryResponse(
            thread_id=thread_id,
            status="awaiting_approval" if pending else values.get("status", "failed"),
            question=values.get("question", ""),
            sql=values.get("sql"),
            summary=values.get("summary"),
            columns=values.get("columns", []),
            rows=values.get("rows", []),
            row_count=values.get("row_count", 0),
            truncated=values.get("truncated", False),
            chart=values.get("chart"),
            estimated_cost=values.get("estimated_cost"),
            attempts=values.get("attempts", 0),
            error=values.get("error"),
            tables=values.get("tables", []),
            approval=ApprovalRequest(**{k: pending[k] for k in ApprovalRequest.model_fields})
            if pending
            else None,
            steps=values.get("steps", []),
        )
        if not pending:  # finished threads are not kept around; only pending approvals need state
            saver = getattr(self.graph, "checkpointer", None)
            if saver is not None and hasattr(saver, "delete_thread"):
                saver.delete_thread(thread_id)
        return response
