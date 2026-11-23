import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

load_dotenv()

connection_url = URL.create(
    drivername="mysql+pymysql",
    username="root",
    password=os.getenv("MYSQL_PASSWORD"),
    host="localhost",
    port=3306,
    database="olist_voc",
    query={"charset": "utf8mb4"},
)
engine = create_engine(connection_url)

OUT_PATH = "data/processed/dev_set_audit_100.csv"


def export_dev_set():
    query = """
        SELECT 
            t.order_id,
            t.review_score,
            COALESCE(m.review_comment_title, '') AS title,
            m.review_comment_message AS message,
            t.primary_issue AS ai_label,
            t.primary_issue AS human_label
        FROM ai_review_tags t
        JOIN vw_order_master m ON t.order_id = m.order_id
        WHERE t.is_dev_set = 1
        ORDER BY t.review_score ASC, t.order_id ASC
    """
    df = pd.read_sql(text(query), engine)
    os.makedirs("data/processed", exist_ok=True)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Exported {len(df)} dev-set reviews to {OUT_PATH}")
    print("\nAI Label breakdown in the 100-review holdout set:")
    print(df["ai_label"].value_counts().to_string())


def score_dev_set():
    df = pd.read_csv(OUT_PATH)
    exact_matches = int((df["ai_label"] == df["human_label"]).sum())
    acc = (exact_matches / len(df)) * 100

    print(f"Holdout Audit Accuracy: {acc:.1f}% ({exact_matches}/{len(df)} exact matches)")

    mismatches = df[df["ai_label"] != df["human_label"]]
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
        export_dev_set()