USE olist_voc;

-- =========================================================================
-- AUDIT 1: Verify exact 5,000 rows & weighted complaint breakdown
-- =========================================================================
SELECT 
    primary_issue,
    COUNT(*) AS sample_reviews,
    ROUND(SUM(sample_weight), 0) AS est_population_reviews,
    ROUND(100.0 * SUM(sample_weight) / SUM(SUM(sample_weight)) OVER (), 2) AS weighted_share_pct
FROM ai_review_tags
GROUP BY primary_issue
ORDER BY est_population_reviews DESC;

-- =========================================================================
-- AUDIT 2: Cross-tab of Star Rating vs. AI Primary Issue (Sanity Check)
-- =========================================================================
SELECT 
    review_score,
    primary_issue,
    COUNT(*) AS cnt
FROM ai_review_tags
GROUP BY review_score, primary_issue
ORDER BY review_score, cnt DESC;

-- =========================================================================
-- POWER BI VIEW 1: vw_pbi_orders (All 99,092 Orders + Primary Category)
-- =========================================================================
CREATE OR REPLACE VIEW vw_pbi_orders AS
WITH primary_product AS (
    SELECT 
        oi.order_id,
        COALESCE(ct.product_category_name_english, p.product_category_name, 'uncategorized') AS category_english,
        ROW_NUMBER() OVER (
            PARTITION BY oi.order_id 
            ORDER BY oi.price DESC, oi.order_item_id ASC
        ) AS rn
    FROM raw_order_items oi
    LEFT JOIN raw_products p ON oi.product_id = p.product_id
    LEFT JOIN raw_category_translation ct ON p.product_category_name = ct.product_category_name
)
SELECT 
    m.order_id,
    m.customer_unique_id,
    m.customer_state,
    m.customer_region,
    DATE(m.order_purchase_timestamp) AS order_date,
    DATE_FORMAT(m.order_purchase_timestamp, '%Y-%m') AS order_month,
    m.order_status,
    m.delivery_outcome,
    m.days_late,
    m.item_count,
    m.distinct_sellers,
    m.items_price,
    m.items_freight,
    m.order_gmv,
    m.freight_ratio,
    COALESCE(pp.category_english, 'uncategorized') AS primary_category,
    m.review_score,
    m.is_low_rating,
    m.has_written_comment,
    m.review_before_delivery
FROM vw_order_master m
LEFT JOIN primary_product pp ON m.order_id = pp.order_id AND pp.rn = 1;

-- =========================================================================
-- POWER BI VIEW 2: vw_pbi_voc_weighted (5,000 AI-Tagged Reviews + Financials)
-- =========================================================================
CREATE OR REPLACE VIEW vw_pbi_voc_weighted AS
SELECT 
    t.order_id,
    t.review_id,
    t.review_score,
    t.primary_issue,
    t.is_complaint,
    t.stratum_pop_n,
    t.stratum_sample_n,
    t.sample_weight,
    t.is_dev_set,
    o.customer_state,
    o.customer_region,
    o.order_date,
    o.order_month,
    o.delivery_outcome,
    o.days_late,
    o.order_gmv,
    o.freight_ratio,
    o.primary_category,
    o.review_before_delivery,
    ROUND(o.order_gmv * t.sample_weight, 2) AS weighted_gmv_associated
FROM ai_review_tags t
JOIN vw_pbi_orders o ON t.order_id = o.order_id;

-- =========================================================================
-- POWER BI VIEW 3: vw_pbi_cohort_retention (90-Day Repeat Purchase Cohort)
-- =========================================================================
CREATE OR REPLACE VIEW vw_pbi_cohort_retention AS
SELECT 
    c.customer_unique_id,
    c.first_order_id,
    DATE(c.first_purchase_ts) AS first_purchase_date,
    DATE(c.first_delivery_ts) AS first_delivery_date,
    c.days_to_next_order,
    c.is_split_basket_7d,
    c.repeat_90d_flag,
    o.customer_state,
    o.customer_region,
    o.delivery_outcome AS first_delivery_outcome,
    o.days_late AS first_days_late,
    o.order_gmv AS first_order_gmv,
    o.primary_category AS first_category,
    o.review_score AS first_review_score,
    t.primary_issue AS first_ai_issue,
    t.sample_weight AS first_ai_sample_weight,
    CASE WHEN t.order_id IS NOT NULL THEN 1 ELSE 0 END AS is_ai_sampled
FROM vw_customer_cohort_90d c
JOIN vw_pbi_orders o ON c.first_order_id = o.order_id
LEFT JOIN ai_review_tags t ON c.first_order_id = t.order_id;

-- =========================================================================
-- AUDIT 3: Cohort Retention & Survey-Weighted AI Retention Verification
-- =========================================================================
SELECT 
    COUNT(*) AS eligible_cohort_customers,
    SUM(is_split_basket_7d) AS split_basket_7d_customers,
    SUM(repeat_90d_flag) AS repeat_90d_customers,
    ROUND(100.0 * AVG(repeat_90d_flag), 2) AS overall_90d_repeat_pct
FROM vw_pbi_cohort_retention;

SELECT 
    first_ai_issue,
    COUNT(*) AS sampled_cohort_customers,
    ROUND(SUM(first_ai_sample_weight), 0) AS est_written_review_cohort,
    ROUND(100.0 * SUM(repeat_90d_flag * first_ai_sample_weight) / SUM(first_ai_sample_weight), 2) AS weighted_90d_repeat_pct
FROM vw_pbi_cohort_retention
WHERE is_ai_sampled = 1
GROUP BY first_ai_issue
ORDER BY weighted_90d_repeat_pct DESC;