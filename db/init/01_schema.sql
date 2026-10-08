-- Demo e-commerce warehouse. Runs automatically on first start of the Postgres container.
CREATE TABLE customers (
    customer_id  SERIAL PRIMARY KEY,
    full_name    TEXT NOT NULL,
    email        TEXT NOT NULL UNIQUE,
    country      TEXT NOT NULL,
    segment      TEXT NOT NULL CHECK (segment IN ('consumer', 'small_business', 'enterprise')),
    signup_date  DATE NOT NULL
);

CREATE TABLE products (
    product_id    SERIAL PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL,
    brand         TEXT NOT NULL,
    unit_price    NUMERIC(10, 2) NOT NULL,
    unit_cost     NUMERIC(10, 2) NOT NULL
);

CREATE TABLE orders (
    order_id     SERIAL PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES customers (customer_id),
    order_date   DATE NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('completed', 'cancelled', 'refunded', 'pending')),
    channel      TEXT NOT NULL CHECK (channel IN ('web', 'mobile_app', 'marketplace', 'retail_store'))
);

CREATE TABLE order_items (
    order_item_id  SERIAL PRIMARY KEY,
    order_id       INT NOT NULL REFERENCES orders (order_id),
    product_id     INT NOT NULL REFERENCES products (product_id),
    quantity       INT NOT NULL CHECK (quantity > 0),
    unit_price     NUMERIC(10, 2) NOT NULL,
    discount_pct   NUMERIC(5, 2) NOT NULL DEFAULT 0
);

CREATE TABLE returns (
    return_id      SERIAL PRIMARY KEY,
    order_item_id  INT NOT NULL REFERENCES order_items (order_item_id),
    return_date    DATE NOT NULL,
    reason         TEXT NOT NULL
);

-- Clickstream table. Intentionally large and unindexed so that careless queries are "expensive".
CREATE TABLE web_events (
    event_id     BIGSERIAL PRIMARY KEY,
    customer_id  INT REFERENCES customers (customer_id),
    event_time   TIMESTAMP NOT NULL,
    event_type   TEXT NOT NULL CHECK (event_type IN ('page_view', 'add_to_cart', 'checkout_start', 'purchase')),
    device       TEXT NOT NULL,
    page         TEXT NOT NULL
);

CREATE INDEX idx_orders_customer ON orders (customer_id);
CREATE INDEX idx_orders_date ON orders (order_date);
CREATE INDEX idx_order_items_order ON order_items (order_id);
CREATE INDEX idx_order_items_product ON order_items (product_id);
