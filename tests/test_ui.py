from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "src" / "sqlagent" / "ui" / "streamlit_app.py")

DONE = {
    "thread_id": "t1",
    "status": "completed",
    "question": "q",
    "sql": "SELECT 1",
    "summary": "All good.",
    "columns": ["country", "n"],
    "rows": [["US", 3], ["DE", 5]],
    "row_count": 2,
    "truncated": False,
    "chart": None,
    "estimated_cost": 12.0,
    "attempts": 1,
    "error": None,
    "tables": ["customers"],
    "approval": None,
    "steps": [{"node": "generate_sql", "detail": "SELECT 1"}],
}
PENDING = {
    **DONE,
    "status": "awaiting_approval",
    "summary": None,
    "rows": [],
    "columns": [],
    "approval": {
        "sql": "SELECT big",
        "estimated_cost": 5e6,
        "estimated_rows": 1e7,
        "threshold": 2e4,
    },
}


def fake_request(calls):
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        body = (
            PENDING
            if url.endswith("/v1/query") and not any("approval" in c[1] for c in calls)
            else DONE
        )
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    return request


def test_ask_shows_summary_and_table(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "request",
        lambda m, u, **k: httpx.Response(200, json=DONE, request=httpx.Request(m, u)),
    )
    at = AppTest.from_file(APP, default_timeout=10).run()
    at.text_area(key="question").set_value("how many customers per country").run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception
    assert any("All good." in s.value for s in at.success)
    assert len(at.dataframe) == 1


def test_expensive_query_shows_approval_flow(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "request", fake_request(calls))
    at = AppTest.from_file(APP, default_timeout=10).run()
    at.text_area(key="question").set_value("something very expensive").run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert any("expensive" in w.value for w in at.warning)
    approve = next(b for b in at.button if b.label == "Approve")
    approve.click().run()
    assert calls[-1][1].endswith("/v1/query/t1/approval") and calls[-1][2] == {"approved": True}
    assert any("All good." in s.value for s in at.success)
