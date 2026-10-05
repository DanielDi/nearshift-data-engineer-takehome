CREATE SCHEMA IF NOT EXISTS analytics;

-- One row per Olist customer_unique_id. customer_id identifies an order-specific record.
CREATE OR REPLACE TABLE analytics.dim_customer AS
SELECT
    customer_unique_id,
    COUNT(*) AS source_customer_ids
FROM raw.customers
GROUP BY customer_unique_id;

-- One row per product_id. Untranslated and missing categories remain visible.
CREATE OR REPLACE TABLE analytics.dim_product AS
SELECT
    p.product_id,
    p.product_category_name AS category_original,
    COALESCE(
        NULLIF(t.product_category_name_english, ''),
        NULLIF(p.product_category_name, ''),
        'uncategorized'
    ) AS category_name
FROM raw.products AS p
LEFT JOIN raw.category_translation AS t
    ON p.product_category_name = t.product_category_name;

-- One row per order_id. Source timestamps have no documented offset.
CREATE OR REPLACE TABLE analytics.fact_order AS
SELECT
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    o.order_status,
    TRY_CAST(o.order_purchase_timestamp AS TIMESTAMP) AS purchased_at,
    TRY_CAST(o.order_approved_at AS TIMESTAMP) AS approved_at,
    TRY_CAST(o.order_delivered_carrier_date AS TIMESTAMP) AS delivered_to_carrier_at,
    TRY_CAST(o.order_delivered_customer_date AS TIMESTAMP) AS delivered_to_customer_at,
    TRY_CAST(o.order_estimated_delivery_date AS TIMESTAMP) AS estimated_delivery_at
FROM raw.orders AS o
LEFT JOIN raw.customers AS c USING (customer_id);

-- One row per (order_id, order_item_id).
CREATE OR REPLACE TABLE analytics.fact_order_item AS
SELECT
    order_id,
    TRY_CAST(order_item_id AS INTEGER) AS order_item_id,
    product_id,
    seller_id,
    TRY_CAST(shipping_limit_date AS TIMESTAMP) AS shipping_limit_at,
    TRY_CAST(price AS DECIMAL(18, 2)) AS item_price,
    TRY_CAST(freight_value AS DECIMAL(18, 2)) AS freight_value
FROM raw.order_items;

-- One row per (order_id, payment_sequential); an order can use several payments.
CREATE OR REPLACE TABLE analytics.fact_payment AS
SELECT
    order_id,
    TRY_CAST(payment_sequential AS INTEGER) AS payment_sequential,
    payment_type,
    TRY_CAST(payment_installments AS INTEGER) AS payment_installments,
    TRY_CAST(payment_value AS DECIMAL(18, 2)) AS payment_value
FROM raw.order_payments;

-- Aggregate each child independently before joining to the order grain.
CREATE OR REPLACE TABLE analytics.mart_order AS
WITH item_totals AS (
    SELECT
        order_id,
        COUNT(*) AS item_rows,
        SUM(item_price) AS item_subtotal,
        SUM(freight_value) AS freight_total
    FROM analytics.fact_order_item
    GROUP BY order_id
),
payment_totals AS (
    SELECT
        order_id,
        COUNT(*) AS payment_rows,
        SUM(payment_value) AS payment_total
    FROM analytics.fact_payment
    GROUP BY order_id
)
SELECT
    o.*,
    COALESCE(i.item_rows, 0) AS item_rows,
    COALESCE(i.item_subtotal, 0) AS item_subtotal,
    COALESCE(i.freight_total, 0) AS freight_total,
    COALESCE(p.payment_rows, 0) AS payment_rows,
    COALESCE(p.payment_total, 0) AS payment_total
FROM analytics.fact_order AS o
LEFT JOIN item_totals AS i USING (order_id)
LEFT JOIN payment_totals AS p USING (order_id);

-- Lifetime repeat rate among customers with at least one delivered order.
CREATE OR REPLACE VIEW analytics.mart_customer_repeat AS
SELECT
    customer_unique_id,
    COUNT(*) AS delivered_orders,
    COUNT(*) >= 2 AS is_repeat_customer
FROM analytics.fact_order
WHERE order_status = 'delivered'
  AND customer_unique_id IS NOT NULL
GROUP BY customer_unique_id;

-- Keep every source month in the mart. The trend flag marks the window used
-- in charts because the months at the dataset edges are sparse.
CREATE OR REPLACE VIEW analytics.mart_monthly_metrics AS
WITH source_months AS (
    SELECT DISTINCT
        CAST(DATE_TRUNC('month', purchased_at) AS DATE) AS purchase_month
    FROM analytics.fact_order
    WHERE purchased_at IS NOT NULL
), delivered AS (
    SELECT
        order_id,
        customer_unique_id,
        purchased_at,
        item_subtotal,
        ROW_NUMBER() OVER (
            PARTITION BY customer_unique_id
            ORDER BY purchased_at, order_id
        ) AS customer_order_number
    FROM analytics.mart_order
    WHERE order_status = 'delivered'
      AND purchased_at IS NOT NULL
), monthly AS (
    SELECT
        CAST(DATE_TRUNC('month', purchased_at) AS DATE) AS purchase_month,
        COUNT(*) AS delivered_orders,
        SUM(item_subtotal) AS merchandise_value,
        COUNT(DISTINCT customer_unique_id) AS active_customers,
        COUNT(DISTINCT CASE WHEN customer_order_number > 1
            THEN customer_unique_id END) AS repeat_customers
    FROM delivered
    GROUP BY 1
)
SELECT
    s.purchase_month,
    COALESCE(m.delivered_orders, 0) AS delivered_orders,
    COALESCE(m.merchandise_value, 0) AS merchandise_value,
    COALESCE(m.active_customers, 0) AS active_customers,
    COALESCE(m.repeat_customers, 0) AS repeat_customers,
    s.purchase_month >= DATE '2017-01-01'
        AND s.purchase_month < DATE '2018-09-01' AS in_trend_window,
    ROUND(m.merchandise_value / NULLIF(m.delivered_orders, 0), 2) AS average_order_value,
    ROUND(m.repeat_customers * 1.0 / NULLIF(m.active_customers, 0), 4)
        AS monthly_repeat_customer_rate
FROM source_months AS s
LEFT JOIN monthly AS m USING (purchase_month);

CREATE OR REPLACE VIEW analytics.mart_category_metrics AS
SELECT
    p.category_name,
    COUNT(*) AS item_rows,
    COUNT(DISTINCT i.order_id) AS delivered_orders,
    SUM(i.item_price) AS merchandise_value
FROM analytics.fact_order_item AS i
JOIN analytics.fact_order AS o USING (order_id)
JOIN analytics.dim_product AS p USING (product_id)
WHERE o.order_status = 'delivered'
GROUP BY p.category_name;

-- Compare calendar dates: Olist's estimated date is stored at midnight.
CREATE OR REPLACE VIEW analytics.mart_delivery AS
SELECT
    order_id,
    purchased_at,
    CAST(delivered_to_customer_at AS DATE) AS actual_delivery_date,
    CAST(estimated_delivery_at AS DATE) AS estimated_delivery_date,
    CAST(delivered_to_customer_at AS DATE)
        > CAST(estimated_delivery_at AS DATE) AS is_late
FROM analytics.fact_order
WHERE order_status = 'delivered'
  AND delivered_to_customer_at IS NOT NULL
  AND estimated_delivery_at IS NOT NULL;
