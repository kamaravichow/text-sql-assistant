# order_items

**Grain:** one row per product line within an order (1 to 4 lines per order).
**Description:** line items of each order with quantity, the unit price at time of sale and the discount applied. Revenue is computed from this table.
**Related tables:** orders, products, returns

| column | type | description |
|---|---|---|
| order_item_id | integer, primary key | Unique line identifier. |
| order_id | integer, foreign key to orders.order_id | Parent order. |
| product_id | integer, foreign key to products.product_id | Product sold. |
| quantity | integer | Units sold on this line (1 to 3). |
| unit_price | numeric(10,2) | Price per unit at the time of sale, before discount. |
| discount_pct | numeric(5,2) | Percentage discount on the line: 0, 5, 10 or 15. |

**Notes:** line revenue = `quantity * unit_price * (1 - discount_pct / 100.0)`. Join `orders` to filter on status and dates, and `products` for category, brand and cost.
**Example questions:** What was total revenue in 2024? Which products generated the most revenue? What is the average discount?
