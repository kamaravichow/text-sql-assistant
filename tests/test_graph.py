import pytest
from conftest import ScriptedLLM, make_service, sql_block

from sqlagent.db import QueryPlan, QueryResult, WarehouseError
from sqlagent.fakes import FakeWarehouse
from sqlagent.service import NoPendingApproval

GOOD = "SELECT status, COUNT(*) AS orders FROM orders GROUP BY status"


def rows_result(sql):
    return QueryResult(columns=["status", "orders"], rows=[["completed", 10], ["cancelled", 2]])


def node_names(response):
    return [s["node"] for s in response.steps]


def test_happy_path_produces_sql_chart_and_summary():
    llm = ScriptedLLM(
        generate=lambda p: sql_block(GOOD),
        chart=lambda p: '{"chart_type": "bar", "x": "status", "y": "orders", "title": "Orders"}',
        summary=lambda p: "Most orders completed.",
    )
    wh = FakeWarehouse(execute=rows_result)
    resp = make_service(llm, wh).ask("How many orders per status?")

    assert resp.status == "completed"
    assert resp.sql == GOOD
    assert resp.rows == [["completed", 10], ["cancelled", 2]]
    assert resp.summary == "Most orders completed."
    assert resp.chart["data"][0]["type"] == "bar"
    assert resp.attempts == 0 and resp.approval is None
    assert node_names(resp) == [
        "retrieve_schema",
        "generate_sql",
        "validate_sql",
        "approval_gate",
        "execute_sql",
        "visualize",
        "summarize",
    ]


def test_self_corrects_a_planner_error():
    def explain(sql):
        if "bad_col" in sql:
            raise WarehouseError('column "bad_col" does not exist')
        return QueryPlan(10, 5)

    llm = ScriptedLLM(
        generate=lambda p: sql_block("SELECT bad_col FROM orders"),
        fix=lambda p: (
            sql_block(GOOD) if 'column "bad_col" does not exist' in p else sql_block("SELECT 0")
        ),
    )
    resp = make_service(llm, FakeWarehouse(explain=explain, execute=rows_result)).ask(
        "orders per status"
    )

    assert resp.status == "completed" and resp.attempts == 1 and resp.sql == GOOD
    assert llm.calls.count("fix_sql") == 1


def test_self_corrects_a_runtime_error():
    def execute(sql):
        if "bad" in sql:
            raise WarehouseError("division by zero")
        return rows_result(sql)

    llm = ScriptedLLM(
        generate=lambda p: sql_block("SELECT 1 /* bad */"), fix=lambda p: sql_block(GOOD)
    )
    wh = FakeWarehouse(execute=execute)
    resp = make_service(llm, wh).ask("orders per status")

    assert resp.status == "completed" and resp.attempts == 1
    assert "execute_sql" in node_names(resp)
    assert wh.executed[-1] == GOOD


def test_unsafe_sql_never_reaches_the_warehouse_and_is_repaired():
    llm = ScriptedLLM(
        generate=lambda p: sql_block("DROP TABLE orders"), fix=lambda p: sql_block(GOOD)
    )
    wh = FakeWarehouse(execute=rows_result)
    resp = make_service(llm, wh).ask("clean up the orders")

    assert resp.status == "completed" and resp.attempts == 1
    assert wh.executed == [GOOD]


def test_gives_up_after_max_retries():
    def explain(sql):
        raise WarehouseError("syntax error at or near FROM")

    llm = ScriptedLLM(
        generate=lambda p: sql_block("SELECT FROM"), fix=lambda p: sql_block("SELECT FROM")
    )
    wh = FakeWarehouse(explain=explain)
    resp = make_service(llm, wh, max_sql_retries=2).ask("anything")

    assert resp.status == "failed" and resp.attempts == 2
    assert llm.calls.count("fix_sql") == 2
    assert "syntax error" in resp.summary and wh.executed == []
    assert node_names(resp)[-1] == "give_up"


def test_unanswerable_question_is_declined_without_touching_the_warehouse():
    llm = ScriptedLLM(generate=lambda p: "CANNOT_ANSWER: there is no weather data.")
    wh = FakeWarehouse()
    resp = make_service(llm, wh).ask("What will the weather be tomorrow?")

    assert resp.status == "unanswerable" and "weather" in resp.summary
    assert resp.sql is None and wh.executed == []


def test_empty_result_still_completes():
    llm = ScriptedLLM(generate=lambda p: sql_block(GOOD))
    wh = FakeWarehouse(execute=lambda sql: QueryResult(columns=["n"], rows=[]))
    resp = make_service(llm, wh).ask("orders per status")
    assert resp.status == "completed" and "no rows" in resp.summary
    assert "summarize" not in llm.calls  # no LLM call needed for an empty result


def test_chart_and_summary_failures_do_not_lose_the_answer():
    def boom(prompt):
        raise RuntimeError("LLM down")

    llm = ScriptedLLM(generate=lambda p: sql_block(GOOD), chart=boom, summary=boom)
    resp = make_service(llm, FakeWarehouse(execute=rows_result)).ask("orders per status")
    assert resp.status == "completed" and resp.rows and "2 row" in resp.summary
    assert resp.chart is not None or "visualize" in node_names(resp)


# ---- human approval checkpoint ---------------------------------------------------------------
EXPENSIVE = QueryPlan(total_cost=5_000_000, plan_rows=1e7)


def expensive_service(**kw):
    llm = ScriptedLLM(generate=lambda p: sql_block(GOOD))
    wh = FakeWarehouse(explain=lambda sql: EXPENSIVE, execute=rows_result)
    return make_service(llm, wh, **kw), wh


def test_expensive_query_pauses_for_approval_then_runs_when_approved():
    service, wh = expensive_service()
    paused = service.ask("orders per status")

    assert paused.status == "awaiting_approval"
    assert paused.approval.estimated_cost == 5_000_000 and paused.approval.sql == GOOD
    assert wh.executed == []  # nothing ran yet

    done = service.resume(paused.thread_id, approved=True)
    assert done.status == "completed" and wh.executed == [GOOD]
    assert any(s["detail"] == "approved by human" for s in done.steps)


def test_rejected_query_is_never_executed():
    service, wh = expensive_service()
    paused = service.ask("orders per status")
    rejected = service.resume(paused.thread_id, approved=False)

    assert rejected.status == "rejected" and wh.executed == []


def test_approval_cannot_be_given_twice_or_for_unknown_threads():
    service, _ = expensive_service()
    paused = service.ask("orders per status")
    service.resume(paused.thread_id, approved=True)
    with pytest.raises(NoPendingApproval):
        service.resume(paused.thread_id, approved=True)
    with pytest.raises(NoPendingApproval):
        service.resume("does-not-exist", approved=True)


def test_cheap_queries_and_disabled_gate_skip_approval():
    llm = ScriptedLLM(generate=lambda p: sql_block(GOOD))
    cheap = make_service(llm, FakeWarehouse(execute=rows_result)).ask("orders per status")
    assert cheap.status == "completed"

    service, wh = expensive_service(require_approval=False)
    assert service.ask("orders per status").status == "completed"


def test_fix_after_approval_does_not_ask_again_if_not_more_expensive():
    calls = {"n": 0}

    def execute(sql):
        calls["n"] += 1
        if calls["n"] == 1:
            raise WarehouseError("canceling statement due to statement timeout")
        return rows_result(sql)

    llm = ScriptedLLM(
        generate=lambda p: sql_block(GOOD), fix=lambda p: sql_block(GOOD + " LIMIT 100")
    )
    wh = FakeWarehouse(explain=lambda sql: EXPENSIVE, execute=execute)
    service = make_service(llm, wh)
    paused = service.ask("orders per status")
    done = service.resume(paused.thread_id, approved=True)
    assert done.status == "completed" and done.attempts == 1
