from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str

    # retrieval
    schema_context: str
    tables: list[str]

    # SQL + self-correction loop
    sql: str
    attempts: int  # self-correction attempts used so far
    error: str | None
    error_stage: str | None  # safety | validation | execution

    # cost gate
    estimated_cost: float | None
    estimated_rows: float | None
    approved_cost: float | None

    # results
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    chart_spec: dict | None
    chart: dict | None
    summary: str

    status: str  # running | completed | failed | rejected | unanswerable
    steps: Annotated[list[dict], operator.add]
