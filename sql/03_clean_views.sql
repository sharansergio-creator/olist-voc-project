USE olist_voc;

-- =========================================================================
-- VIEW 1: vw_order_master (1 row per order_id, Jan 2017 - Aug 2018)
-- =========================================================================
CREATE OR REPLACE VIEW vw_order_master AS
WITH agg_items AS (
    SELECT 
        order_id,
        COUNT(*) AS item_count,
        COUNT(DISTINCT seller_id) AS distinct_sellers,
        SUM(price) AS items_price,
        SUM(freight_value) AS items_freight,
        SUM(price + freight_value) AS order_gmv
    FROM raw_order_items
    GROUP BY order_id
),
agg_payments AS (
    SELECT 
        order_id,
        SUM(payment_value) AS total_payment_value,
        MAX(payment_installments) AS max_installments
    FROM raw_order_payments
    GROUP BY order_id
),
dedup_reviews AS (
    SELECT 
        row_num,
        review_id,
        order_id,
        review_score,
        review_comment_title,
        review_comment_message,
        review_creation_date,
        review_answer_timestamp,
        ROW_NUMBER() OVER (
            PARTITION BY order_id 
            ORDER BY review_creation_date DESC, review_answer_timestamp DESC, review_id DESC
        ) AS rn
    FROM raw_order_reviews
)
SELECT 
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_state,
    -- Collapse 27 Brazilian states into 5 official macro-regions
    CASE 
        WHEN c.customer_state IN ('SP', 'RJ', 'MG', 'ES') THEN 'Southeast'
        WHEN c.customer_state IN ('PR', 'SC', 'RS') THEN 'South'
        WHEN c.customer_state IN ('BA', 'PE', 'CE', 'MA', 'PB', 'RN', 'AL', 'SE', 'PI') THEN 'Northeast'
        WHEN c.customer_state IN ('DF', 'GO', 'MT', 'MS') THEN 'Central-West'
        ELSE 'North'
    END AS customer_region,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    
    -- Grain-safe financial metrics (fallback to payment value if canceled order has no items)
    COALESCE(i.item_count, 0) AS item_count,
    COALESCE(i.distinct_sellers, 0) AS distinct_sellers,
    COALESCE(i.items_price, 0.00) AS items_price,
    COALESCE(i.items_freight, 0.00) AS items_freight,
    COALESCE(i.order_gmv, p.total_payment_value, 0.00) AS order_gmv,
    COALESCE(p.total_payment_value, 0.00) AS total_payment_value,
    CASE 
        WHEN COALESCE(i.order_gmv, 0) > 0 THEN ROUND(i.items_freight / i.order_gmv, 4)
        ELSE NULL 
    END AS freight_ratio,

    -- Exact SLA & Delivery Outcome classification
    CASE
        WHEN o.order_delivered_customer_date IS NOT NULL 
             AND o.order_delivered_customer_date < o.order_purchase_timestamp 
            THEN 'Date Anomaly'
        WHEN o.order_status IN ('canceled', 'unavailable') 
             AND o.order_delivered_customer_date IS NULL 
            THEN 'Never Arrived'
        WHEN o.order_status = 'delivered' 
             AND o.order_delivered_customer_date IS NULL 
            THEN 'Delivered - Missing Actual Date'
        WHEN o.order_status = 'delivered' 
             AND o.order_estimated_delivery_date IS NULL 
            THEN 'Delivered - Missing Estimate'
        WHEN o.order_status = 'delivered' 
             AND DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date) 
            THEN 'SLA Breached'
        WHEN o.order_status = 'delivered' 
             AND DATE(o.order_delivered_customer_date) <= DATE(o.order_estimated_delivery_date) 
            THEN 'On Time'
        ELSE 'Pending / Other'
    END AS delivery_outcome,

    CASE 
        WHEN o.order_status = 'delivered' 
             AND o.order_delivered_customer_date IS NOT NULL 
             AND o.order_estimated_delivery_date IS NOT NULL
            THEN DATEDIFF(DATE(o.order_delivered_customer_date), DATE(o.order_estimated_delivery_date))
        ELSE NULL
    END AS days_late,

    -- Deduplicated primary review fields
    r.review_id,
    r.review_score,
    CASE WHEN r.review_score IN (1, 2) THEN 1 ELSE 0 END AS is_low_rating,
    r.review_comment_title,
    r.review_comment_message,
    CASE WHEN r.review_comment_message IS NOT NULL THEN 1 ELSE 0 END AS has_written_comment,
    r.review_creation_date,
    r.review_answer_timestamp,
    CASE 
        WHEN o.order_delivered_customer_date IS NOT NULL 
             AND r.review_creation_date IS NOT NULL
             AND r.review_creation_date < o.order_delivered_customer_date 
            THEN 1 
        ELSE 0 
    END AS review_before_delivery

FROM raw_orders o
JOIN raw_customers c ON o.customer_id = c.customer_id
LEFT JOIN agg_items i ON o.order_id = i.order_id
LEFT JOIN agg_payments p ON o.order_id = p.order_id
LEFT JOIN dedup_reviews r ON o.order_id = r.order_id AND r.rn = 1
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp < '2018-09-01';


-- =========================================================================
-- VIEW 2: vw_customer_cohort_90d (1 row per unique delivered customer)
-- =========================================================================
CREATE OR REPLACE VIEW vw_customer_cohort_90d AS
WITH delivered_orders AS (
    SELECT 
        c.customer_unique_id,
        o.order_id,
        o.order_purchase_timestamp,
        o.order_delivered_customer_date,
        ROW_NUMBER() OVER (
            PARTITION BY c.customer_unique_id 
            ORDER BY o.order_purchase_timestamp ASC, o.order_id ASC
        ) AS delivered_seq
    FROM raw_orders o
    JOIN raw_customers c ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_delivered_customer_date >= o.order_purchase_timestamp
),
first_orders AS (
    SELECT 
        customer_unique_id,
        order_id AS first_order_id,
        order_purchase_timestamp AS first_purchase_ts,
        order_delivered_customer_date AS first_delivery_ts
    FROM delivered_orders
    WHERE delivered_seq = 1
      AND order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp < '2018-09-01'
      -- Must have full 90-day observation window before 2018-08-31
      AND DATE(order_delivered_customer_date) <= DATE_SUB('2018-08-31', INTERVAL 90 DAY)
),
subsequent_orders AS (
    SELECT 
        f.customer_unique_id,
        MIN(DATEDIFF(DATE(v.order_purchase_timestamp), DATE(f.first_delivery_ts))) AS days_to_next_order,
        MAX(
            CASE 
                WHEN DATEDIFF(DATE(v.order_purchase_timestamp), DATE(f.first_delivery_ts)) BETWEEN 0 AND 6 
                THEN 1 ELSE 0 
            END
        ) AS is_split_basket_7d,
        MAX(
            CASE 
                WHEN DATEDIFF(DATE(v.order_purchase_timestamp), DATE(f.first_delivery_ts)) BETWEEN 7 AND 90 
                THEN 1 ELSE 0 
            END
        ) AS repeat_90d_flag
    FROM first_orders f
    JOIN raw_customers c ON f.customer_unique_id = c.customer_unique_id
    JOIN raw_orders v 
      ON c.customer_id = v.customer_id
     AND v.order_id <> f.first_order_id
     AND v.order_status NOT IN ('canceled', 'unavailable')
     AND DATE(v.order_purchase_timestamp) >= DATE(f.first_delivery_ts)
    GROUP BY f.customer_unique_id
)
SELECT 
    f.customer_unique_id,
    f.first_order_id,
    f.first_purchase_ts,
    f.first_delivery_ts,
    s.days_to_next_order,
    COALESCE(s.is_split_basket_7d, 0) AS is_split_basket_7d,
    COALESCE(s.repeat_90d_flag, 0) AS repeat_90d_flag
FROM first_orders f
LEFT JOIN subsequent_orders s ON f.customer_unique_id = s.customer_unique_id;

-- Quick Verification Check:
SELECT 
    COUNT(*) AS total_clean_orders,
    COUNT(DISTINCT order_id) AS unique_orders,
    SUM(has_written_comment) AS eligible_written_reviews,
    ROUND(SUM(order_gmv), 2) AS total_gmv_brl
FROM vw_order_master;