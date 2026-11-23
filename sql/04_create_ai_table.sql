USE olist_voc;

CREATE TABLE IF NOT EXISTS ai_review_tags (
    order_id VARCHAR(50) PRIMARY KEY,
    review_id VARCHAR(50) NOT NULL,
    review_score INT NOT NULL,
    stratum_pop_n INT NOT NULL,          -- Total eligible written reviews in this star rating (N_h)
    stratum_sample_n INT NOT NULL,       -- Sampled reviews in this star rating (n_h)
    sample_weight DECIMAL(10, 4) NOT NULL, -- Exact weight: N_h / n_h
    primary_issue VARCHAR(50) NOT NULL,
    is_complaint TINYINT(1) NOT NULL,
    is_dev_set TINYINT(1) NOT NULL DEFAULT 0, -- 1 = random 100-review human-audit slice
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);