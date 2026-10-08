# web_events

**Grain:** one row per clickstream event (about 300,000 rows). This is the largest table and has no secondary indexes.
**Description:** website and app behaviour events used for funnel and engagement analysis.
**Related tables:** customers

| column | type | description |
|---|---|---|
| event_id | bigint, primary key | Unique event identifier. |
| customer_id | integer, nullable foreign key to customers.customer_id | NULL for anonymous visitors (about 30% of events). |
| event_time | timestamp | When the event happened (2023-01-01 to 2024-12-31). |
| event_type | text | `page_view`, `add_to_cart`, `checkout_start` or `purchase`. |
| device | text | `desktop`, `mobile` or `tablet`. |
| page | text | `/home`, `/search`, `/product`, `/cart`, `/checkout` or `/account`. |

**Notes:** always filter by `event_time` where possible and avoid joining this table to `order_items` without aggregating first; a naive join multiplies rows and is very expensive. Funnel steps follow the order page_view, add_to_cart, checkout_start, purchase.
**Example questions:** How many events happen per device? What is the funnel drop-off between add_to_cart and purchase?
