"""Streamlit front-end for the REST API.   streamlit run src/sqlagent/ui/streamlit_app.py"""

from __future__ import annotations

import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
TIMEOUT = float(os.getenv("API_TIMEOUT", "180"))

EXAMPLES = [
    "What was revenue by month in 2024?",
    "Which 5 product categories have the highest revenue?",
    "What is the return rate by product category?",
    "What is the web conversion rate by device?",
]


def call(method: str, path: str, **kwargs) -> dict:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    response = httpx.request(method, f"{API_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    return response.json()


def show_result(result: dict) -> None:
    status = result["status"]
    if status == "completed":
        st.success(result["summary"])
    elif status in ("failed", "rejected", "unanswerable"):
        st.warning(
            f"**{status.capitalize()}.** {result.get('summary') or result.get('error') or ''}"
        )

    if result.get("chart"):
        st.plotly_chart(go.Figure(result["chart"]), use_container_width=True)
    if result.get("columns") and result.get("rows"):
        st.dataframe(
            pd.DataFrame(result["rows"], columns=result["columns"]), use_container_width=True
        )
        if result.get("truncated"):
            st.caption("Result truncated at the row cap.")

    with st.expander("SQL and agent steps"):
        if result.get("sql"):
            st.code(result["sql"], language="sql")
        cost = result.get("estimated_cost")
        st.caption(
            f"Tables: {', '.join(result.get('tables', []))} · self-corrections: {result.get('attempts', 0)}"
            + (f" · planner cost: {cost:,.0f}" if cost is not None else "")
        )
        for step in result.get("steps", []):
            st.text(f"{step['node']}: {step['detail']}")


def main() -> None:
    st.set_page_config(page_title="Text-to-SQL Analytics Assistant", page_icon="📊", layout="wide")
    st.title("📊 Text-to-SQL Analytics Assistant")
    st.caption(
        "Ask a business question in plain English. The agent writes, validates and runs the SQL."
    )

    with st.sidebar:
        st.subheader("Examples")
        for example in EXAMPLES:
            if st.button(example, use_container_width=True):
                st.session_state["question"] = example
        st.caption(f"API: {API_URL}")

    question = st.text_area("Question", key="question", height=80, placeholder=EXAMPLES[0])
    if st.button("Ask", type="primary", disabled=len(question.strip()) < 3):
        with st.spinner("Thinking..."):
            try:
                st.session_state["result"] = call("POST", "/v1/query", json={"question": question})
            except httpx.HTTPError as exc:
                st.session_state["result"] = None
                st.error(f"Request failed: {exc}")

    result = st.session_state.get("result")
    if not result:
        return

    if result["status"] == "awaiting_approval":
        approval = result["approval"]
        st.warning(
            f"This query looks expensive (planner cost {approval['estimated_cost']:,.0f} > "
            f"threshold {approval['threshold']:,.0f}). Review it before it runs."
        )
        st.code(approval["sql"], language="sql")
        approve, reject, _ = st.columns([1, 1, 6])
        decision = None
        if approve.button("Approve", type="primary"):
            decision = True
        if reject.button("Reject"):
            decision = False
        if decision is not None:
            with st.spinner("Running..."):
                try:
                    st.session_state["result"] = call(
                        "POST",
                        f"/v1/query/{result['thread_id']}/approval",
                        json={"approved": decision},
                    )
                except httpx.HTTPError as exc:
                    st.error(f"Request failed: {exc}")
            st.rerun()
    else:
        show_result(result)


main()
