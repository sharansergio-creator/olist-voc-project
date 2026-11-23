import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

load_dotenv()

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

OUT_PATH = "data/processed/dev_set_audit_100.csv"

VALID_CATEGORIES = {
    "Delivery Delay / Non-Arrival",
    "Damaged / Defective Item",
    "Wrong / Incomplete Order",
    "Product Quality / Expectation Mismatch",
    "Seller / Support Communication",
    "Positive / Other",
}


def export_blind_dev_set(force: bool = False):
    if os.path.exists(OUT_PATH) and not force:
        raise FileExistsError(
            f"{OUT_PATH} already exists with human annotations. "
            "Pass --force-export only if you intentionally want to overwrite it with a blank blind sheet."
        )

    query = """
        SELECT 
            t.order_id,
            t.review_score,
            COALESCE(m.review_comment_title, '') AS title,
            m.review_comment_message AS message,
            '' AS human_label
        FROM ai_review_tags t
        JOIN vw_order_master m ON t.order_id = m.order_id
        WHERE t.is_dev_set = 1
        ORDER BY t.review_score ASC, t.order_id ASC
    """
    df = pd.read_sql(text(query), engine)
    os.makedirs("data/processed", exist_ok=True)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Exported {len(df)} blind audit reviews to {OUT_PATH} (ai_label withheld for unbiased human annotation).")


def score_dev_set():
    if not os.path.exists(OUT_PATH):
        raise FileNotFoundError(f"Missing {OUT_PATH}. Run with --force-export and annotate human_label first.")

    human_df = pd.read_csv(OUT_PATH).fillna("")
    if "human_label" not in human_df.columns:
        raise ValueError("Missing 'human_label' column in dev_set_audit_100.csv")

    if len(human_df) != 100:
        raise ValueError(f"Expected exactly 100 rows in {OUT_PATH}, found {len(human_df)}.")

    if human_df["order_id"].duplicated().any():
        raise ValueError(f"Duplicate order_id entries found in {OUT_PATH}.")

    unlabeled = human_df[~human_df["human_label"].isin(VALID_CATEGORIES)]
    if not unlabeled.empty:
        raise ValueError(
            f"Found {len(unlabeled)} rows in {OUT_PATH} without a valid taxonomy label in 'human_label'."
        )

    ai_query = """
        SELECT order_id, primary_issue AS ai_label
        FROM ai_review_tags
        WHERE is_dev_set = 1
    """
    ai_df = pd.read_sql(text(ai_query), engine)

    if set(human_df["order_id"]) != set(ai_df["order_id"]):
        raise ValueError("Audit CSV order_id set does not match MySQL is_dev_set = 1 IDs.")

    merged = human_df.drop(columns=["ai_label"], errors="ignore").merge(ai_df, on="order_id", how="inner")

    if len(merged) != 100:
        raise ValueError(f"Expected 100 matched audit rows, found {len(merged)}.")

    exact_matches = int((merged["ai_label"] == merged["human_label"]).sum())
    acc = (exact_matches / len(merged)) * 100

    print(f"Human-Audit Agreement (Blind Human Labels vs. MySQL AI Tags): {acc:.1f}% ({exact_matches}/{len(merged)} exact matches)")

    mismatches = merged[merged["ai_label"] != merged["human_label"]]
    if not mismatches.empty:
        print("\nEdge-Case Disagreements:")
        print(
            mismatches[["order_id", "review_score", "ai_label", "human_label"]].to_string(
                index=False
            )
        )


if __name__ == "__main__":
    if "--score" in sys.argv:
        score_dev_set()
    else:
        export_blind_dev_set(force="--force-export" in sys.argv)