# returns

**Grain:** one row per returned order line.
**Description:** items sent back by customers, with the return date and a reason code. About 5% of items from completed or refunded orders are returned.
**Related tables:** order_items

| column | type | description |
|---|---|---|
| return_id | integer, primary key | Unique return identifier. |
| order_item_id | integer, foreign key to order_items.order_item_id | The order line that was returned. |
| return_date | date | Day the return was registered (never later than 2024-12-31). |
| reason | text | `defective`, `wrong_item`, `changed_mind` or `arrived_late`. |

**Notes:** to attribute returns to a product, customer or order, join `returns` to `order_items` and onwards.
**Example questions:** What is the return rate by category? What are the most common return reasons?
