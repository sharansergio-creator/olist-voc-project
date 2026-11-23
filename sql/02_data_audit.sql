USE olist_voc;

-- CHECK 1: Monthly order counts (Why we restrict to Jan 2017 - Aug 2018)
SELECT 
    DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS order_month,
    COUNT(*) AS total_orders
FROM raw_orders
GROUP BY order_month
ORDER BY order_month;

-- CHECK 2: Order statuses & missing delivery dates
SELECT 
    order_status,
    COUNT(*) AS order_count,
    SUM(CASE WHEN order_delivered_customer_date IS NULL THEN 1 ELSE 0 END) AS missing_delivered_date
FROM raw_orders
GROUP BY order_status
ORDER BY order_count DESC;

-- CHECK 3: Duplicate reviews check (Orders vs Review IDs)
SELECT 
    COUNT(*) AS total_review_rows,
    COUNT(DISTINCT review_id) AS unique_review_ids,
    COUNT(DISTINCT order_id) AS unique_order_ids
FROM raw_order_reviews;

-- CHECK 4: Selection bias check — Comment rate by Star Rating (Jan 2017 - Aug 2018)
SELECT 
    r.review_score,
    COUNT(*) AS total_reviews,
    SUM(CASE WHEN r.review_comment_message IS NOT NULL THEN 1 ELSE 0 END) AS reviews_with_text,
    ROUND(100.0 * SUM(CASE WHEN r.review_comment_message IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS comment_rate_pct
FROM raw_order_reviews r
JOIN raw_orders o ON r.order_id = o.order_id
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp < '2018-09-01'
GROUP BY r.review_score
ORDER BY r.review_score;