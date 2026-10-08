from __future__ import annotations

import re
from pathlib import Path

import pytest

from sqlagent.config import Settings
from sqlagent.db import QueryPlan
from sqlagent.fakes import FakeWarehouse, FunctionChatModel
from sqlagent.graph import build_graph
from sqlagent.nodes import Deps
from sqlagent.retrieval import SchemaRetriever, TfidfRetriever, load_table_docs
from sqlagent.service import AgentService

ROOT = Path(__file__).resolve().parents[1]


def make_settings(**overrides) -> Settings:
    base = dict(
        llm_model="test-model",
        docs_dir=ROOT / "docs" / "tables",
        glossary_path=ROOT / "docs" / "glossary.md",
        require_approval=True,
        approval_cost_threshold=1_000.0,
        max_sql_retries=2,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def sql_block(sql: str) -> str:
    return f"Plan.\n```sql\n{sql}\n```"


class ScriptedLLM:
    """Builds a FunctionChatModel from per-task handlers keyed on the prompt's [task: ...] tag."""

    def __init__(self, generate, fix=None, chart=None, summary=None):
        self.calls: list[str] = []
        self.handlers = {
            "generate_sql": generate,
            "fix_sql": fix or (lambda p: sql_block("SELECT 1")),
            "choose_chart": chart or (lambda p: '{"chart_type": "none"}'),
            "summarize": summary or (lambda p: "Summary text."),
        }

    def __call__(self, prompt: str) -> str:
        task = re.search(r"\[task: (\w+)\]", prompt).group(1)
        self.calls.append(task)
        return self.handlers[task](prompt)

    def model(self) -> FunctionChatModel:
        return FunctionChatModel(fn=self)


def make_service(llm: ScriptedLLM, warehouse: FakeWarehouse, **settings_overrides) -> AgentService:
    settings = make_settings(**settings_overrides)
    docs = load_table_docs(settings.docs_dir)
    deps = Deps(
        llm=llm.model(),
        retriever=SchemaRetriever(docs, TfidfRetriever(docs), top_k=3),
        warehouse=warehouse,
        settings=settings,
        glossary="glossary",
    )
    return AgentService(build_graph(deps), settings)


@pytest.fixture
def plan():
    return QueryPlan
