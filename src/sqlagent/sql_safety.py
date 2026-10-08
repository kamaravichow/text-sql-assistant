"""Static validation of LLM-written SQL before it gets anywhere near the warehouse.

This is one layer of defence. The others are a read-only database role, a read-only
transaction, a statement timeout and a row cap (see ``db.py``).
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

ALLOWED_SCHEMAS = {"", "public"}

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    t
    for t in (
        getattr(exp, name, None)
        for name in (
            "Insert",
            "Update",
            "Delete",
            "Merge",
            "Create",
            "Drop",
            "Alter",
            "AlterTable",
            "TruncateTable",
            "Command",
            "Copy",
            "Grant",
            "Revoke",
            "Set",
            "Use",
            "Transaction",
            "Commit",
            "Rollback",
            "Into",
            "Lock",
        )
    )
    if t is not None
)

FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "set_config",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "dblink",
    "dblink_exec",
    "pg_reload_conf",
    "current_setting",
    "copy",
}


class UnsafeSQLError(ValueError):
    """The statement is not a single, read-only SELECT over the public schema."""


def check_sql(sql: str) -> str:
    """Return the cleaned statement or raise :class:`UnsafeSQLError` with a fixable message."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQLError("The query is empty.")
    try:
        statements = [s for s in sqlglot.parse(cleaned, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSQLError(f"SQL syntax error: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("Exactly one SQL statement is allowed.")

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise UnsafeSQLError("Only SELECT queries are allowed (WITH ... SELECT is fine).")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeSQLError(
                f"Forbidden construct: {type(node).__name__}. Write a plain read-only SELECT."
            )
        if isinstance(node, exp.Table):
            schema = (node.db or "").lower()
            if schema not in ALLOWED_SCHEMAS:
                raise UnsafeSQLError(f"Schema '{node.db}' is not accessible; use tables in public.")
        if isinstance(node, (exp.Func, exp.Anonymous)):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in FORBIDDEN_FUNCTIONS:
                raise UnsafeSQLError(f"Function {name}() is not allowed.")
    return cleaned
