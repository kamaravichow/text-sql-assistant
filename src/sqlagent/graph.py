from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .config import Settings
from .nodes import Deps, Nodes, make_routers
from .state import AgentState


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver | None = None):
    """Wire the agent.

    START -> retrieve_schema -> generate_sql -> validate_sql -> approval_gate -> execute_sql
             -> visualize -> summarize -> END
    with validate_sql / execute_sql failures looping through fix_sql (bounded), then give_up.
    """
    n = Nodes(deps)
    after_generate, after_check, after_approval = make_routers(deps.settings.max_sql_retries)

    g = StateGraph(AgentState)
    g.add_node("retrieve_schema", n.retrieve_schema)
    g.add_node("generate_sql", n.generate_sql)
    g.add_node("validate_sql", n.validate_sql)
    g.add_node("fix_sql", n.fix_sql)
    g.add_node("approval_gate", n.approval_gate)
    g.add_node("execute_sql", n.execute_sql)
    g.add_node("visualize", n.visualize)
    g.add_node("summarize", n.summarize)
    g.add_node("give_up", n.give_up)

    g.add_edge(START, "retrieve_schema")
    g.add_edge("retrieve_schema", "generate_sql")
    g.add_conditional_edges(
        "generate_sql", after_generate, {"validate_sql": "validate_sql", "end": END}
    )
    g.add_conditional_edges(
        "validate_sql",
        after_check,
        {"fix_sql": "fix_sql", "give_up": "give_up", "next": "approval_gate"},
    )
    g.add_edge("fix_sql", "validate_sql")
    g.add_conditional_edges(
        "approval_gate", after_approval, {"execute_sql": "execute_sql", "end": END}
    )
    g.add_conditional_edges(
        "execute_sql",
        after_check,
        {"fix_sql": "fix_sql", "give_up": "give_up", "next": "visualize"},
    )
    g.add_edge("visualize", "summarize")
    g.add_edge("summarize", END)
    g.add_edge("give_up", END)

    # An in-process checkpointer is required for interrupt(); swap in PostgresSaver for multi-worker.
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def build_default_graph(settings: Settings, checkpointer: BaseCheckpointSaver | None = None):
    from .db import PostgresWarehouse
    from .llm import build_llm
    from .retrieval import build_retriever

    glossary = (
        settings.glossary_path.read_text(encoding="utf-8")
        if settings.glossary_path.exists()
        else ""
    )
    deps = Deps(
        llm=build_llm(settings),
        retriever=build_retriever(settings),
        warehouse=PostgresWarehouse(
            settings.warehouse_dsn, settings.statement_timeout_ms, settings.max_rows
        ),
        settings=settings,
        glossary=glossary,
    )
    return build_graph(deps, checkpointer)
