# E-Commerce Voice of Customer (VoC) & Logistics SLA Analytics Pipeline

An end-to-end analytics engineering and AI text-classification pipeline built on the Brazilian Olist E-Commerce dataset (**99,092 orders**; **R$ 15.94M GMV**). Combines **MySQL**, **Python (Pydantic + Gemini Structured Outputs)**, **Horvitz-Thompson weighted survey estimation**, and a **3-page Power BI executive dashboard** to quantify how delivery SLA breaches and operational failures drive 1–2 star reviews and suppress 90-day repeat purchases.

---

## Key Analytical Findings

- **Logistics SLA Impact on Customer Satisfaction:** Across **99,092 orders** (`R$ 15.94M` GMV; defined as item price + freight, tracked separately from collected payment value)[cite: 11], the overall SLA breach rate is **6.79%** and low-rating (`1★–2★`) rate is **14.63%**[cite: 11]. However, low ratings jump from **9.25%** on `On Time` deliveries to **62.42%** when `SLA Breached` and **80.66%** when `Never Arrived`[cite: 11].
- **Volume vs. Revenue Exposure (`R$ 3.00M` Weighted GMV Associated with Complaints):**
  - **Delivery Delay / Non-Arrival** is the #1 complaint by volume (**14.09%** of all 40,494 written reviews), followed by **Wrong / Incomplete Order** (**10.30%**)[cite: 12].
  - By expansion-weighted GMV associated with complaint-affected orders, **Wrong / Incomplete Order** overtakes delivery delays (**R$ 0.99M** vs. **R$ 0.97M**) because higher-AOV orders suffer disproportionately from fulfillment and picking errors[cite: 12].
- **90-Day Repeat Purchase Retention & Churn Penalty (`N = 73,075` Eligible Delivered First-Time Buyers):**
  - Overall 90-day repeat purchase rate sits at **0.95%**[cite: 10], dropping from **0.97%** after an `On Time` delivery to **0.65%** after an `SLA Breached` delivery (**33% relative drop**)[cite: 10].
  - Across the survey-weighted AI review cohort (`is_ai_sampled = 1`), 90-day repeat purchasing stands at **1.11%** for `Positive / Other` reviews (`2.35%` for `Seller / Support Communication`, where responsive recovery can retain buyers) and **1.16%** for `Wrong / Incomplete Order` (often replacement re-orders), but collapses to **0.51%** for `Delivery Delay / Non-Arrival`, **0.17%** for `Damaged / Defective Item`, and **0.16%** for `Product Quality / Expectation Mismatch` (**~85% relative drop** vs. `Positive / Other`)[cite: 10].

---

## Executive Dashboard Preview

### 1. Executive Overview & Logistics SLA Impact
![Executive Overview](assets/page1_executive_overview.png)

### 2. AI Voice of Customer (Weighted Root Causes & Associated GMV)
![AI Voice of Customer](assets/page2_ai_voc.png)

### 3. 90-Day Cohort Retention & Churn Penalty
![90-Day Cohort Retention](assets/page3_cohort_retention.png)

---

## Architecture & Engineering Decisions

1. **Relational Data Warehouse & Grain-Safe Modeling (`MySQL`)**
   - Loaded and indexed **7 raw relational tables** (`sql/01_create_tables.sql`, `src/01_load_data.py`), audited anomalies (`sql/02_data_audit.sql`), and built **5 analytical & BI views** (`sql/03_clean_views.sql`, `sql/05_audit_and_pbi_views.sql`) into `vw_order_master` (**99,092 orders**), pre-aggregating `raw_order_items` and `raw_order_payments` to the order grain prior to joining to prevent multi-item / split-payment revenue fan-out and deduplicating multi-review orders using customer `review_creation_date`.
   - Engineered delivery SLA outcomes (`On Time`, `SLA Breached`, `Never Arrived`, `days_late`), regional macro-groupings, and a delivery-anchored 90-day cohort retention view (`vw_customer_cohort_90d`, **73,075 eligible first-time delivered buyers** with a full 90-day observation window prior to `2018-08-31`), evaluating 7-day split-basket orders (`Days 0–6`) independently from true 90-day repeat orders (`Days 7–90`).

2. **LLM Structured Classification & Horvitz-Thompson Weighting (`Python` + `Gemini API`)**
   - Sorted the **40,494 written-comment population** deterministically by `(review_score, order_id)` and drew a reproducible star-stratified sample (**5,000 written Portuguese reviews**: 1,000 per star rating `1★–5★`).
   - Built an idempotent, checkpointed micro-batching pipeline (`src/02_classify_reviews.py`) with **Pydantic schema enforcement**, exact batch `order_id` completeness assertions, and multi-model fallback (`gemini-3.5-flash-lite` / `gemini-3.8-flash` / `gemini-4-hydrogen`) to classify reviews into 6 mutually exclusive operational categories.
   - Validated classification quality against an **independent 100-review human-annotated holdout set (`is_dev_set = 1`)** stored in `data/processed/dev_set_audit_100.csv` and scored directly against MySQL `ai_review_tags`, achieving **98.0% exact-match accuracy (98/100)** (`python src/04_audit_dev_set.py --score`).
   - Applied exact inverse-probability stratum weights (`sample_weight = N_stratum / n_stratum`) to project unbiased population complaint rates, associated GMV, and survey-weighted AI-issue repeat rates across all 40,494 written reviews.

3. **Executive BI Semantic Model (`Power BI Desktop`)**
   - Built a 3-table `1:1` single-direction semantic model (`vw_pbi_orders`, `vw_pbi_voc_weighted`, `vw_pbi_cohort_retention`) with 9 custom DAX measures (including Horvitz-Thompson survey-weighted retention) and a custom JSON report theme (`powerbi/olist_executive_theme.json`).

---

## Reproducibility & Setup

```bash
# 1. Clone repository & install dependencies
git clone [https://github.com/sharansergio-creator/olist-voc-project.git](https://github.com/sharansergio-creator/olist-voc-project.git)
cd olist-voc-project
pip install -r requirements.txt

# 2. Configure environment variables
cp .env.example .env
# Add your GEMINI_API_KEY and MYSQL_PASSWORD to .env

# 3. Initialize MySQL schema, load data, and run LLM classification
mysql -u root -p < sql/01_create_tables.sql
python src/01_load_data.py
mysql -u root -p < sql/02_data_audit.sql
mysql -u root -p < sql/03_clean_views.sql
mysql -u root -p < sql/04_create_ai_table.sql
python src/02_classify_reviews.py
mysql -u root -p < sql/05_audit_and_pbi_views.sql

# 4. Verify holdout audit accuracy & export Power BI CSVs
python src/04_audit_dev_set.py --score
python src/03_export_for_pbi.py
```

---

## Repository Structure

```text
olist-voc-project/
├── assets/
│   ├── page1_executive_overview.png
│   ├── page2_ai_voc.png
│   └── page3_cohort_retention.png
├── data/
│   └── processed/
│       ├── dev_set_audit_100.csv
│       ├── vw_pbi_cohort_retention.csv
│       ├── vw_pbi_orders.csv
│       └── vw_pbi_voc_weighted.csv
├── powerbi/
│   ├── olist_executive_theme.json
│   └── olist_voc_dashboard.pbix
├── sql/
│   ├── 01_create_tables.sql
│   ├── 02_data_audit.sql
│   ├── 03_clean_views.sql
│   ├── 04_create_ai_table.sql
│   └── 05_audit_and_pbi_views.sql
├── src/
│   ├── 01_load_data.py
│   ├── 02_classify_reviews.py
│   ├── 03_export_for_pbi.py
│   └── 04_audit_dev_set.py
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```