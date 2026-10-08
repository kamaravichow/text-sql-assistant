"""LangGraph nodes. Each node is a small, separately testable function of the agent state."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from . import prompts
from .charts import ChartSpec, build_figure, heuristic_spec, parse_spec, to_dataframe
from .config import Settings
from .db import Warehouse, WarehouseError
from .llm import message_text
from .retrieval import SchemaRetriever
from .sql_safety import UnsafeSQLError, check_sql
from .state import AgentState

SQL_BLOCK = re.compile(r"```(?:sql|postgresql|pgsql)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
PREVIEW_ROWS = 25


def extract_sql(text: str) -> str | None:
    blocks = SQL_BLOCK.findall(text)
    if blocks:
        return blocks[-1].strip()
    stripped = text.strip()
    if re.match(r"(?is)^(with|select)\b", stripped):
        return stripped
    return None


def extract_refusal(text: str) -> str | None:
    match = re.search(r"CANNOT_ANSWER:\s*(.+)", text)
    return match.group(1).strip() if match else None


def _step(node: str, detail: str) -> dict:
    return {"node": node, "detail": detail}


def _preview(columns: list[str], rows: list[list[Any]], limit: int = PREVIEW_ROWS) -> str:
    return "\n".join(
        json.dumps(dict(zip(columns, row, strict=False)), default=str) for row in rows[:limit]
    )


@dataclass
class Deps:
    llm: BaseChatModel
    retriever: SchemaRetriever
    warehouse: Warehouse
    settings: Settings
    glossary: str = ""


class Nodes:
    def __init__(self, deps: Deps):
        self.d = deps

    # ---- retrieval -------------------------------------------------------------------------
    def retrieve_schema(self, state: AgentState) -> dict:
        docs = self.d.retriever.retrieve(state["question"])
        context = "\n\n---\n\n".join(doc.text for doc in docs)
        names = [doc.name for doc in docs]
        return {
            "schema_context": context,
            "tables": names,
            "status": "running",
            "steps": [_step("retrieve_schema", f"tables: {', '.join(names)}")],
        }

    # ---- generation ------------------------------------------------------------------------
    def generate_sql(self, state: AgentState) -> dict:
        system = prompts.GENERATE_SYSTEM.format(
            today=prompts.today_line(self.d.settings.as_of_date),
            glossary=self.d.glossary,
            schema=state["schema_context"],
        )
        reply = message_text(
            self.d.llm.invoke(
                [
                    SystemMessage(system),
                    HumanMessage(prompts.GENERATE_USER.format(question=state["question"])),
                ]
            )
        )
        sql = extract_sql(reply)
        if sql:
            return {
                "sql": sql,
                "attempts": 0,
                "error": None,
                "error_stage": None,
                "steps": [_step("generate_sql", sql)],
            }
        refusal = extract_refusal(reply)
        if refusal:
            return {
                "status": "unanswerable",
                "summary": refusal,
                "steps": [_step("generate_sql", f"cannot answer: {refusal}")],
            }
        return {
            "status": "failed",
            "error": "The model did not return a SQL query.",
            "summary": "I could not turn that question into a SQL query.",
            "steps": [_step("generate_sql", "no SQL in model reply")],
        }

    def fix_sql(self, state: AgentState) -> dict:
        system = prompts.FIX_SYSTEM.format(glossary=self.d.glossary, schema=state["schema_context"])
        user = prompts.FIX_USER.format(
            question=state["question"],
            sql=state["sql"],
            stage=state.get("error_stage") or "error",
            error=state["error"],
        )
        reply = message_text(self.d.llm.invoke([SystemMessage(system), HumanMessage(user)]))
        attempt = state.get("attempts", 0) + 1
        sql = extract_sql(reply) or state["sql"]
        return {
            "sql": sql,
            "attempts": attempt,
            "steps": [
                _step(
                    "fix_sql", f"attempt {attempt} after {state.get('error_stage')} error -> {sql}"
                )
            ],
        }

    # ---- validation + cost gate --------------------------------------------------------------
    def validate_sql(self, state: AgentState) -> dict:
        try:
            sql = check_sql(state["sql"])
        except UnsafeSQLError as exc:
            return {
                "error": str(exc),
                "error_stage": "safety",
                "steps": [_step("validate_sql", f"rejected by safety check: {exc}")],
            }
        try:
            plan = self.d.warehouse.explain(sql)
        except WarehouseError as exc:
            return {
                "sql": sql,
                "error": str(exc),
                "error_stage": "validation",
                "steps": [_step("validate_sql", f"EXPLAIN failed: {exc}")],
            }
        return {
            "sql": sql,
            "error": None,
            "error_stage": None,
            "estimated_cost": plan.total_cost,
            "estimated_rows": plan.plan_rows,
            "steps": [_step("validate_sql", f"ok, planner cost {plan.total_cost:,.0f}")],
        }

    def approval_gate(self, state: AgentState) -> dict:
        s = self.d.settings
        cost = state.get("estimated_cost") or 0.0
        previously = state.get("approved_cost")
        needs_approval = (
            s.require_approval
            and cost > s.approval_cost_threshold
            and not (previously is not None and cost <= previously)
        )
        if not needs_approval:
            return {"steps": [_step("approval_gate", f"auto-approved (cost {cost:,.0f})")]}

        # Execution pauses here; the graph resumes with Command(resume={"approved": bool}).
        decision = interrupt(
            {
                "type": "approval_required",
                "question": state["question"],
                "sql": state["sql"],
                "estimated_cost": cost,
                "estimated_rows": state.get("estimated_rows"),
                "threshold": s.approval_cost_threshold,
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        if approved:
            return {"approved_cost": cost, "steps": [_step("approval_gate", "approved by human")]}
        return {
            "status": "rejected",
            "summary": "The query was not run: a reviewer declined the expensive query.",
            "steps": [_step("approval_gate", "rejected by human")],
        }

    # ---- execution -------------------------------------------------------------------------
    def execute_sql(self, state: AgentState) -> dict:
        try:
            result = self.d.warehouse.execute(state["sql"])
        except WarehouseError as exc:
            return {
                "error": str(exc),
                "error_stage": "execution",
                "steps": [_step("execute_sql", f"failed: {exc}")],
            }
        return {
            "error": None,
            "error_stage": None,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "steps": [_step("execute_sql", f"{result.row_count} rows")],
        }

    def give_up(self, state: AgentState) -> dict:
        attempts = state.get("attempts", 0)
        return {
            "status": "failed",
            "summary": (
                f"I could not produce a working query after {attempts} correction attempt(s). "
                f"Last error: {state.get('error')}"
            ),
            "steps": [_step("give_up", f"{state.get('error_stage')} error: {state.get('error')}")],
        }

    # ---- presentation ----------------------------------------------------------------------
    def visualize(self, state: AgentState) -> dict:
        columns, rows = state.get("columns", []), state.get("rows", [])
        try:
            df = to_dataframe(columns, rows)
            spec: ChartSpec | None = None
            if len(df) > 1:
                reply = message_text(
                    self.d.llm.invoke(
                        [
                            SystemMessage(prompts.CHART_SYSTEM),
                            HumanMessage(
                                prompts.CHART_USER.format(
                                    question=state["question"],
                                    columns=columns,
                                    rows=_preview(columns, rows, 8),
                                )
                            ),
                        ]
                    )
                )
                spec = parse_spec(reply, df)
            spec = spec or heuristic_spec(df)
            figure = build_figure(spec, df)
        except Exception as exc:  # a chart must never cost the user their answer
            return {
                "chart": None,
                "chart_spec": None,
                "steps": [_step("visualize", f"skipped: {exc}")],
            }
        return {
            "chart": figure,
            "chart_spec": spec.model_dump(),
            "steps": [_step("visualize", spec.chart_type)],
        }

    def summarize(self, state: AgentState) -> dict:
        columns, rows = state.get("columns", []), state.get("rows", [])
        row_count = state.get("row_count", len(rows))
        if not rows:
            summary = "The query ran successfully but returned no rows."
        else:
            try:
                reply = self.d.llm.invoke(
                    [
                        SystemMessage(prompts.SUMMARY_SYSTEM),
                        HumanMessage(
                            prompts.SUMMARY_USER.format(
                                question=state["question"],
                                columns=columns,
                                row_count=row_count,
                                truncated=" (truncated at the row cap)"
                                if state.get("truncated")
                                else "",
                                shown=min(PREVIEW_ROWS, len(rows)),
                                rows=_preview(columns, rows),
                            )
                        ),
                    ]
                )
                summary = message_text(reply).strip()
            except Exception as exc:  # fall back to a plain description
                summary = f"The query returned {row_count} row(s). (Summary unavailable: {exc})"
        return {"summary": summary, "status": "completed", "steps": [_step("summarize", "done")]}


# ---- routing -------------------------------------------------------------------------------
def make_routers(max_retries: int):
    def after_generate(state: AgentState) -> str:
        return "validate_sql" if state.get("sql") and state.get("status") == "running" else "end"

    def after_check(state: AgentState) -> str:
        """Used after validate_sql and execute_sql: loop through fix_sql until retries run out."""
        if state.get("error"):
            return "fix_sql" if state.get("attempts", 0) < max_retries else "give_up"
        return "next"

    def after_approval(state: AgentState) -> str:
        return "end" if state.get("status") == "rejected" else "execute_sql"

    return after_generate, after_check, after_approval
