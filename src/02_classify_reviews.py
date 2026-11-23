import os
import time
import argparse
from typing import Literal, List
import pandas as pd
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# 1. Connect to MySQL
connection_url = URL.create(
    drivername="mysql+pymysql",
    username=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD"),
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    database=os.getenv("MYSQL_DB", "olist_voc"),
    query={"charset": "utf8mb4"},
)
engine = create_engine(connection_url)

# 2. Initialize Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Models to rotate across automatically if one experiences a 503 demand spike or quota limit
MODELS_TO_TRY = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
]

# 3. Strict 6-Category Taxonomy enforced by Pydantic
IssueCategory = Literal[
    "Delivery Delay / Non-Arrival",
    "Damaged / Defective Item",
    "Wrong / Incomplete Order",
    "Product Quality / Expectation Mismatch",
    "Seller / Support Communication",
    "Positive / Other",
]


class SingleReviewResult(BaseModel):
    order_id: str = Field(description="The exact order_id provided for this review.")
    primary_issue: IssueCategory = Field(
        description="The single main issue reported in the Portuguese customer review, or 'Positive / Other' if no complaint is stated."
    )
    is_complaint: bool = Field(
        description="True if the customer describes any problem, delay, defect, or dissatisfaction; False otherwise."
    )

    @model_validator(mode="after")
    def enforce_consistency(self):
        self.is_complaint = self.primary_issue != "Positive / Other"
        return self


class BatchClassificationResponse(BaseModel):
    results: List[SingleReviewResult]


SYSTEM_PROMPT = """
You are an expert e-commerce Quality & Customer Experience Analyst reading Brazilian Portuguese customer reviews.
For EACH review in the input list, return its exact `order_id` and classify it into ONE primary issue category based ONLY on the written text:

1. "Delivery Delay / Non-Arrival": Late delivery, item not received yet, tracking stuck, or carrier issues.
2. "Damaged / Defective Item": Product arrived broken, scratched, leaking, malfunctioning, or dead on arrival.
3. "Wrong / Incomplete Order": Wrong color/size/model sent, missing parts/accessories, or missing items from a multi-item order.
4. "Product Quality / Expectation Mismatch": Item works/arrived intact, but material feels cheap, smaller/different than photos, or poor value.
5. "Seller / Support Communication": Unresponsive seller, difficulty canceling/returning/refunding, or rude customer support.
6. "Positive / Other": Praise, generic satisfaction ("bom", "recomendo", "tudo certo"), or neutral/unclear text with no identifiable complaint.

Rules:
- Return one entry for EVERY input review with its exact matching `order_id`.
- If a review mentions multiple issues, pick the PRIMARY/most severe operational failure (e.g., Non-Arrival or Damaged Item over Support).
- Rely strictly on the review text.
"""


def build_stratified_sample(sample_per_star: int = 1000, seed: int = 42) -> pd.DataFrame:
    query = """
        SELECT 
            order_id,
            review_id,
            review_score,
            COALESCE(review_comment_title, '') AS title,
            review_comment_message AS message
        FROM vw_order_master
        WHERE has_written_comment = 1
          AND review_score BETWEEN 1 AND 5
        ORDER BY review_score ASC, order_id ASC
    """
    df = pd.read_sql(text(query), engine)
    df = df.sort_values(["review_score", "order_id"]).reset_index(drop=True)

    sampled_parts = []
    for star in [1, 2, 3, 4, 5]:
        stratum = df[df["review_score"] == star]
        n_pop = len(stratum)
        n_samp = min(sample_per_star, n_pop)
        sub = stratum.sample(n=n_samp, random_state=seed).copy()
        sub["stratum_pop_n"] = n_pop
        sub["stratum_sample_n"] = n_samp
        sub["sample_weight"] = round(n_pop / n_samp, 4)
        sampled_parts.append(sub)

    full_sample = pd.concat(sampled_parts, ignore_index=True)
    full_sample = full_sample.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    full_sample["is_dev_set"] = 0
    full_sample.loc[:99, "is_dev_set"] = 1
    return full_sample


def classify_micro_batch(chunk_df: pd.DataFrame, max_retries: int = 6) -> dict[str, SingleReviewResult]:
    expected_ids = set(chunk_df["order_id"])
    items_text = [
        f"- order_id: {r['order_id']} | title: {r['title']} | review: {r['message']}"
        for _, r in chunk_df.iterrows()
    ]
    prompt = "Classify these reviews:\n" + "\n".join(items_text)

    for attempt in range(1, max_retries + 1):
        model_name = MODELS_TO_TRY[(attempt - 1) % len(MODELS_TO_TRY)]
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=BatchClassificationResponse,
                    temperature=0.0,
                ),
            )
            parsed = BatchClassificationResponse.model_validate_json(response.text)

            returned_ids = [item.order_id for item in parsed.results]
            if len(returned_ids) != len(expected_ids):
                raise ValueError(f"Expected {len(expected_ids)} results, got {len(returned_ids)}")
            if len(set(returned_ids)) != len(returned_ids):
                raise ValueError("Duplicate order_id entries returned in batch")
            if set(returned_ids) != expected_ids:
                raise ValueError("Returned order_ids do not match submitted batch")

            return {item.order_id: item for item in parsed.results}
        except Exception as e:
            wait_sec = min(4 * attempt, 20)
            print(f"  Attempt {attempt}/{max_retries} ({model_name}) error ({e}). Retrying in {wait_sec}s...")
            time.sleep(wait_sec)

    return {}


def run_pipeline(limit: int | None = None, batch_size: int = 100):
    sample_df = build_stratified_sample(sample_per_star=1000, seed=42)

    existing = pd.read_sql(text("SELECT order_id FROM ai_review_tags"), engine)
    already_done = set(existing["order_id"])
    todo_df = sample_df[~sample_df["order_id"].isin(already_done)].copy()

    if limit:
        todo_df = todo_df.head(limit)

    total_todo = len(todo_df)
    print(f"Target sample: {len(sample_df):,} | Already in DB: {len(already_done):,} | Remaining: {total_todo:,}")

    processed_now = 0
    for start in range(0, total_todo, batch_size):
        chunk = todo_df.iloc[start : start + batch_size]
        res_map = classify_micro_batch(chunk)

        rows_to_insert = []
        for _, row in chunk.iterrows():
            oid = row["order_id"]
            if oid in res_map:
                res = res_map[oid]
                rows_to_insert.append({
                    "order_id": oid,
                    "review_id": row["review_id"],
                    "review_score": int(row["review_score"]),
                    "stratum_pop_n": int(row["stratum_pop_n"]),
                    "stratum_sample_n": int(row["stratum_sample_n"]),
                    "sample_weight": float(row["sample_weight"]),
                    "primary_issue": res.primary_issue,
                    "is_complaint": int(res.is_complaint),
                    "is_dev_set": int(row["is_dev_set"]),
                })

        if rows_to_insert:
            pd.DataFrame(rows_to_insert).to_sql("ai_review_tags", con=engine, if_exists="append", index=False)
            processed_now += len(rows_to_insert)
            print(f"  Saved {len(rows_to_insert)} rows -> Total in DB: {len(already_done) + processed_now:,} / {len(sample_df):,}")

        time.sleep(1.0)

    print("\nBatch run complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for a quick test")
    args = parser.parse_args()
    run_pipeline(limit=args.limit)