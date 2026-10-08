# products

**Grain:** one row per product in the catalogue (120 products, 15 per category).
**Description:** product catalogue with list price and unit cost, used for category and margin analysis.
**Related tables:** order_items

| column | type | description |
|---|---|---|
| product_id | integer, primary key | Unique product identifier. |
| product_name | text | Product name, e.g. "Electronics Item 3". |
| category | text | One of: Electronics, Home & Kitchen, Books, Clothing, Sports, Beauty, Toys, Grocery. |
| brand | text | One of: Acme, Globex, Initech, Umbrella, Hooli. |
| unit_price | numeric(10,2) | Current list price. |
| unit_cost | numeric(10,2) | Cost of goods per unit; always lower than `unit_price`. |

**Notes:** revenue should be computed from `order_items.unit_price` (price at time of sale), not `products.unit_price`. Cost always comes from `products.unit_cost`.
**Example questions:** Which category has the highest gross margin? Which brand sells the most units?
