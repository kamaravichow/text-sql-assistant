import pytest

from sqlagent.sql_safety import UnsafeSQLError, check_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select * from orders;",
        "WITH t AS (SELECT customer_id FROM orders) SELECT COUNT(*) FROM t",
        "SELECT a FROM orders UNION ALL SELECT a FROM orders",
        "SELECT o.order_id FROM public.orders o WHERE o.order_date >= DATE '2024-01-01'",
        "SELECT DATE_TRUNC('month', order_date)::date, COUNT(*) FILTER (WHERE status = 'completed') FROM orders GROUP BY 1",
    ],
)
def test_allows_read_only_selects(sql):
    assert check_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "DELETE FROM orders",
        "UPDATE orders SET status = 'completed'",
        "INSERT INTO customers (full_name) VALUES ('x')",
        "SELECT 1; DROP TABLE orders",
        "SELECT * INTO backup FROM orders",
        "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT pg_sleep(30)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT * FROM information_schema.tables",
        "COPY orders TO '/tmp/x'",
        "SET ROLE postgres",
        "",
        "   ;  ",
        "SELEC nope FROM",
    ],
)
def test_rejects_unsafe_or_invalid(sql):
    with pytest.raises(UnsafeSQLError):
        check_sql(sql)


def test_strips_trailing_semicolon():
    assert check_sql("SELECT 1;") == "SELECT 1"
