# customers

**Grain:** one row per customer account.
**Description:** customer master data: where the customer is, which commercial segment they belong to and when they signed up.
**Related tables:** orders, web_events

| column | type | description |
|---|---|---|
| customer_id | integer, primary key | Unique customer identifier. |
| full_name | text | Display name (synthetic, e.g. "Customer 17"). |
| email | text, unique | Contact e-mail address. |
| country | text | One of: United States, United Kingdom, Germany, France, India, Canada, Australia, Brazil. |
| segment | text | `consumer`, `small_business` or `enterprise`. |
| signup_date | date | Day the account was created (2022-01-01 to 2024-06-30). |

**Notes:** join to `orders` on `customer_id` to analyse purchasing behaviour by country or segment.
**Example questions:** How many customers signed up per country? Which segment spends the most?
