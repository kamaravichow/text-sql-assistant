# Business definitions

These definitions are injected into every SQL-generation prompt. Use them exactly.

- **Data coverage:** orders span 2022-01-10 to 2024-12-31. `web_events` spans 2023-01-01 to 2024-12-31.
- **Revenue (net revenue):** `SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount_pct / 100.0))`
  over items that belong to orders with `orders.status = 'completed'`. Cancelled, refunded and pending orders never count as revenue.
- **Gross margin:** revenue minus cost, where cost is `SUM(order_items.quantity * products.unit_cost)` over the same completed-order items.
- **Order count:** `COUNT(DISTINCT orders.order_id)`; unless the user asks otherwise, count only `completed` orders.
- **Average order value (AOV):** revenue divided by the number of completed orders.
- **Active customer:** a customer with at least one completed order in the period being asked about.
- **Return rate:** returned order items divided by order items sold (`COUNT(returns.return_id) / COUNT(order_items.order_item_id)`), counted over items of completed or refunded orders.
- **Conversion rate (web):** share of distinct customers with a `purchase` event among distinct customers with any event; anonymous events (`customer_id IS NULL`) are excluded.
- **Time periods:** use `DATE_TRUNC` for month / quarter / year buckets. Quarter and year labels follow the calendar year.
