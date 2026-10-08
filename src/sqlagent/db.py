from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import psycopg
from langsmith import traceable


class WarehouseError(RuntimeError):
    """A database-side failure (syntax error, unknown column, timeout, ...)."""


@dataclass
class QueryPlan:
    total_cost: float
    plan_rows: float


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool = False
    row_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.row_count = len(self.rows)


class Warehouse(Protocol):
    def explain(self, sql: str) -> QueryPlan: ...

    def execute(self, sql: str) -> QueryResult: ...


def jsonable(value: Any) -> Any:
    """Convert DB values to JSON-safe primitives."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    return str(value)


class PostgresWarehouse:
    """Read-only access to PostgreSQL: one short-lived read-only transaction per call."""

    def __init__(self, dsn: str, statement_timeout_ms: int = 15_000, max_rows: int = 1000):
        self.dsn = dsn
        self.statement_timeout_ms = statement_timeout_ms
        self.max_rows = max_rows

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(
            self.dsn, options=f"-c statement_timeout={self.statement_timeout_ms}"
        )
        conn.read_only = True
        return conn

    @traceable(name="warehouse.explain", run_type="tool")
    def explain(self, sql: str) -> QueryPlan:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
                payload = cur.fetchone()[0]
        except psycopg.Error as exc:
            raise WarehouseError(_clean_error(exc)) from exc
        plan = payload[0]["Plan"] if isinstance(payload, list) else payload["Plan"]
        return QueryPlan(total_cost=float(plan["Total Cost"]), plan_rows=float(plan["Plan Rows"]))

    @traceable(name="warehouse.execute", run_type="tool")
    def execute(self, sql: str) -> QueryResult:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(sql)
                columns = [d.name for d in cur.description or []]
                fetched = cur.fetchmany(self.max_rows + 1)
        except psycopg.Error as exc:
            raise WarehouseError(_clean_error(exc)) from exc
        truncated = len(fetched) > self.max_rows
        rows = [[jsonable(v) for v in row] for row in fetched[: self.max_rows]]
        return QueryResult(columns=columns, rows=rows, truncated=truncated)

    def ping(self) -> bool:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False


def _clean_error(exc: psycopg.Error) -> str:
    diag = getattr(exc, "diag", None)
    message = getattr(diag, "message_primary", None) or str(exc)
    hint = getattr(diag, "message_hint", None)
    return f"{message} (hint: {hint})" if hint else message
