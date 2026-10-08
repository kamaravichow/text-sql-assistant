# orders

**Grain:** one row per customer order (header level; line items live in `order_items`).
**Description:** order headers with the order date, lifecycle status and sales channel. This is the main fact table for sales analysis.
**Related tables:** customers, order_items

| column | type | description |
|---|---|---|
| order_id | integer, primary key | Unique order identifier. |
| customer_id | integer, foreign key to customers.customer_id | The customer who placed the order. |
| order_date | date | Day the order was placed (2022-01-10 to 2024-12-31). |
| status | text | `completed`, `cancelled`, `refunded` or `pending`. About 85% of orders are completed. |
| channel | text | `web`, `mobile_app`, `marketplace` or `retail_store`. |

**Notes:** only `status = 'completed'` orders count towards revenue (see business definitions). The order total is not stored; derive it from `order_items`.
**Example questions:** How many orders were placed per month? Which channel has the most orders? What share of orders were cancelled?
