-- Deterministic synthetic data (fixed seed) covering 2023-01-01 .. 2024-12-31.
SELECT setseed(0.42);

INSERT INTO customers (full_name, email, country, segment, signup_date)
SELECT 'Customer ' || g,
       'customer' || g || '@example.com',
       (ARRAY['United States','United Kingdom','Germany','France','India','Canada','Australia','Brazil'])[1 + floor(random() * 8)::int],
       (ARRAY['consumer','consumer','consumer','small_business','small_business','enterprise'])[1 + floor(random() * 6)::int],
       DATE '2022-01-01' + floor(random() * 912)::int
FROM generate_series(1, 2000) g;

INSERT INTO products (product_name, category, brand, unit_price, unit_cost)
SELECT category || ' Item ' || n, category, brand, price, round((price * (0.40 + random() * 0.30))::numeric, 2)
FROM (
    SELECT c.category,
           n,
           (ARRAY['Acme','Globex','Initech','Umbrella','Hooli'])[1 + (n % 5)] AS brand,
           round((c.base_price * (0.5 + random() * 1.5))::numeric, 2) AS price
    FROM (VALUES ('Electronics', 180.0), ('Home & Kitchen', 60.0), ('Books', 18.0), ('Clothing', 45.0),
                 ('Sports', 70.0), ('Beauty', 28.0), ('Toys', 30.0), ('Grocery', 12.0)) AS c (category, base_price)
    CROSS JOIN generate_series(1, 15) n
) p
ORDER BY category, n;

INSERT INTO orders (customer_id, order_date, status, channel)
SELECT c.customer_id,
       c.signup_date + floor(r.r_date * (DATE '2024-12-31' - c.signup_date + 1))::int,
       CASE WHEN r.r_status < 0.85 THEN 'completed'
            WHEN r.r_status < 0.92 THEN 'cancelled'
            WHEN r.r_status < 0.96 THEN 'refunded'
            ELSE 'pending' END,
       CASE WHEN r.r_channel < 0.45 THEN 'web'
            WHEN r.r_channel < 0.75 THEN 'mobile_app'
            WHEN r.r_channel < 0.90 THEN 'marketplace'
            ELSE 'retail_store' END
FROM (
    SELECT g,
           1 + floor(random() * 2000)::int AS cid,
           random() AS r_date,
           random() AS r_status,
           random() AS r_channel
    FROM generate_series(1, 20000) g
) r
JOIN customers c ON c.customer_id = r.cid
ORDER BY r.g;

INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount_pct)
SELECT i.order_id,
       p.product_id,
       i.qty,
       p.unit_price,
       (ARRAY[0, 0, 0, 5, 10, 15])[1 + i.disc]
FROM (
    SELECT o.order_id,
           k,
           1 + floor(random() * 120)::int AS pid,
           1 + floor(random() * 3)::int AS qty,
           floor(random() * 6)::int AS disc
    FROM orders o
    CROSS JOIN LATERAL generate_series(1, 1 + (o.order_id % 4)) k
) i
JOIN products p ON p.product_id = i.pid
ORDER BY i.order_id, i.k;

INSERT INTO returns (order_item_id, return_date, reason)
SELECT x.order_item_id,
       LEAST(x.order_date + 3 + floor(x.r_days * 25)::int, DATE '2024-12-31'),
       CASE WHEN x.r_reason < 0.35 THEN 'defective'
            WHEN x.r_reason < 0.60 THEN 'wrong_item'
            WHEN x.r_reason < 0.85 THEN 'changed_mind'
            ELSE 'arrived_late' END
FROM (
    SELECT oi.order_item_id, o.order_date, random() AS r_days, random() AS r_reason
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.status IN ('completed', 'refunded') AND random() < 0.05
) x
ORDER BY x.order_item_id;

INSERT INTO web_events (customer_id, event_time, event_type, device, page)
SELECT CASE WHEN e.r_anon < 0.30 THEN NULL ELSE 1 + floor(e.r_cust * 2000)::int END,
       TIMESTAMP '2023-01-01' + e.r_time * INTERVAL '730 days',
       CASE WHEN e.r_type < 0.70 THEN 'page_view'
            WHEN e.r_type < 0.85 THEN 'add_to_cart'
            WHEN e.r_type < 0.93 THEN 'checkout_start'
            ELSE 'purchase' END,
       (ARRAY['desktop','mobile','tablet'])[1 + floor(e.r_dev * 3)::int],
       (ARRAY['/home','/search','/product','/cart','/checkout','/account'])[1 + floor(e.r_page * 6)::int]
FROM (
    SELECT g, random() AS r_anon, random() AS r_cust, random() AS r_time,
           random() AS r_type, random() AS r_dev, random() AS r_page
    FROM generate_series(1, 300000) g
) e
ORDER BY e.g;

ANALYZE;
