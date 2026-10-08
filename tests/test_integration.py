"""Needs the demo warehouse (``docker compose up db``) reachable via WAREHOUSE_DSN."""

from __future__ import annotations

import re

import pytest
from conftest import ROOT, ScriptedLLM, make_settings

from sqlagent.db import PostgresWarehouse, WarehouseError
from sqlagent.evaluation import evaluate_case, load_benchmark, summarize_results
from sqlagent.graph import build_graph
from sqlagent.nodes import Deps
from sqlagent.retrieval import SchemaRetriever, TfidfRetriever, load_table_docs
from sqlagent.service import AgentService
from sqlagent.sql_safety import check_sql

pytestmark = pytest.mark.integration

SETTINGS = make_settings()
CASES = load_benchmark(ROOT / "eval" / "benchmark.jsonl")


@pytest.fixture(scope="module")
def warehouse():
    wh = PostgresWarehouse(SETTINGS.warehouse_dsn, statement_timeout_ms=15_000, max_rows=1000)
    if not wh.ping():
        pytest.skip("warehouse not reachable")
    return wh


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_gold_sql_is_safe_and_runs(warehouse, case):
    assert check_sql(case.gold_sql)
    assert warehouse.explain(case.gold_sql).total_cost > 0
    assert warehouse.execute(case.gold_sql).row_count > 0


def test_documented_columns_exist_in_the_database(warehouse):
    for doc in load_table_docs(SETTINGS.docs_dir):
        documented = re.findall(r"^\|\s*(\w+)\s*\|", doc.text, flags=re.MULTILINE)
        documented = [c for c in documented if c not in {"column"}]
        result = warehouse.execute(f"SELECT * FROM {doc.name} LIMIT 1")
        assert set(documented) == set(result.columns), doc.name


def test_warehouse_is_read_only_and_reports_errors(warehouse):
    with pytest.raises(WarehouseError):
        warehouse.execute("DELETE FROM orders")
    with pytest.raises(WarehouseError, match="does not exist"):
        warehouse.explain("SELECT nope FROM orders")


def test_row_cap_truncates(warehouse):
    small = PostgresWarehouse(SETTINGS.warehouse_dsn, max_rows=5)
    result = small.execute("SELECT * FROM web_events")
    assert result.row_count == 5 and result.truncated


def test_statement_timeout_is_enforced():
    fast = PostgresWarehouse(SETTINGS.warehouse_dsn, statement_timeout_ms=50)
    with pytest.raises(WarehouseError, match="timeout"):
        fast.execute("SELECT COUNT(*) FROM web_events a CROSS JOIN web_events b")


def test_agent_end_to_end_with_oracle_llm(warehouse):
    """The full graph against the real database, with an LLM stub that answers with the gold SQL."""
    gold = {c.question: c.gold_sql for c in CASES}

    def generate(prompt):
        question = re.search(r"Question: (.+)", prompt).group(1).strip()
        return f"```sql\n{gold[question]}\n```"

    llm = ScriptedLLM(generate=generate)
    docs = load_table_docs(SETTINGS.docs_dir)
    settings = make_settings(require_approval=False)
    deps = Deps(llm.model(), SchemaRetriever(docs, TfidfRetriever(docs)), warehouse, settings, "")
    service = AgentService(build_graph(deps), settings)

    results = [evaluate_case(service, warehouse, c) for c in CASES]
    assert all(r.correct for r in results), [r for r in results if not r.correct]
    assert summarize_results(results)["execution_accuracy"] == 1.0


def test_expensive_cross_join_triggers_approval(warehouse):
    sql = "SELECT COUNT(*) AS n FROM web_events a CROSS JOIN customers b"
    llm = ScriptedLLM(generate=lambda p: f"```sql\n{sql}\n```")
    docs = load_table_docs(SETTINGS.docs_dir)
    settings = make_settings(approval_cost_threshold=20_000)
    deps = Deps(llm.model(), SchemaRetriever(docs, TfidfRetriever(docs)), warehouse, settings, "")
    service = AgentService(build_graph(deps), settings)
    resp = service.ask("count every event for every customer")
    assert resp.status == "awaiting_approval" and resp.approval.estimated_cost > 20_000
    assert service.resume(resp.thread_id, approved=False).status == "rejected"


def test_harness_scores_wrong_answers_as_wrong(warehouse):
    """Negative control: an agent that always answers 'SELECT COUNT(*) FROM orders' must score ~0."""
    llm = ScriptedLLM(generate=lambda p: "```sql\nSELECT COUNT(*) AS n FROM orders\n```")
    docs = load_table_docs(SETTINGS.docs_dir)
    settings = make_settings(require_approval=False)
    deps = Deps(llm.model(), SchemaRetriever(docs, TfidfRetriever(docs)), warehouse, settings, "")
    service = AgentService(build_graph(deps), settings)

    results = [evaluate_case(service, warehouse, c) for c in CASES]
    assert summarize_results(results)["execution_accuracy"] < 0.1
