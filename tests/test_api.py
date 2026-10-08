from conftest import ScriptedLLM, make_service, make_settings, sql_block
from fastapi.testclient import TestClient

from sqlagent.api.main import create_app
from sqlagent.db import QueryPlan, QueryResult
from sqlagent.fakes import FakeWarehouse

GOOD = "SELECT status, COUNT(*) AS orders FROM orders GROUP BY status"


def client(cost=10.0, api_key=""):
    llm = ScriptedLLM(generate=lambda p: sql_block(GOOD))
    wh = FakeWarehouse(
        explain=lambda sql: QueryPlan(cost, 100),
        execute=lambda sql: QueryResult(columns=["status", "orders"], rows=[["completed", 10]]),
    )
    service = make_service(llm, wh)
    settings = make_settings(api_key=api_key)
    return TestClient(create_app(service=service, settings=settings)), wh


def test_query_endpoint_returns_structured_answer():
    c, _ = client()
    r = c.post("/v1/query", json={"question": "orders per status"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed" and body["sql"] == GOOD
    assert body["columns"] == ["status", "orders"] and body["summary"]


def test_expensive_query_requires_approval_via_second_call():
    c, wh = client(cost=9e6)
    first = c.post("/v1/query", json={"question": "orders per status"}).json()
    assert first["status"] == "awaiting_approval" and first["approval"]["estimated_cost"] == 9e6
    assert wh.executed == []

    done = c.post(f"/v1/query/{first['thread_id']}/approval", json={"approved": True}).json()
    assert done["status"] == "completed" and wh.executed == [GOOD]


def test_approval_for_unknown_thread_is_404():
    c, _ = client()
    assert c.post("/v1/query/nope/approval", json={"approved": True}).status_code == 404


def test_validation_errors_are_422():
    c, _ = client()
    assert c.post("/v1/query", json={"question": "x"}).status_code == 422
    assert c.post("/v1/query", json={}).status_code == 422


def test_api_key_is_enforced_when_configured():
    c, _ = client(api_key="s3cret")
    body = {"question": "orders per status"}
    assert c.post("/v1/query", json=body).status_code == 401
    assert c.post("/v1/query", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/v1/query", json=body, headers={"X-API-Key": "s3cret"}).status_code == 200


def test_tables_endpoint_lists_documented_tables():
    c, _ = client()
    names = {t["name"] for t in c.get("/v1/tables").json()}
    assert {"orders", "order_items", "web_events"} <= names
