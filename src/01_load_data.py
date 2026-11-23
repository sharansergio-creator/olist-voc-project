import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

mysql_password = os.getenv("MYSQL_PASSWORD")
if not mysql_password:
    raise RuntimeError("MYSQL_PASSWORD is not set. Add it to your .env file.")

# 1. Database connection settings loaded from environment variables
connection_url = URL.create(
    drivername="mysql+pymysql",
    username=os.getenv("MYSQL_USER", "root"),
    password=mysql_password,
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    database=os.getenv("MYSQL_DB", "olist_voc"),
    query={"charset": "utf8mb4"},
)

engine = create_engine(connection_url)

# 2. Map each MySQL table to its CSV file in data/raw
RAW_DIR = "data/raw"

FILES_MAP = {
    "raw_customers": "olist_customers_dataset.csv",
    "raw_orders": "olist_orders_dataset.csv",
    "raw_order_items": "olist_order_items_dataset.csv",
    "raw_order_payments": "olist_order_payments_dataset.csv",
    "raw_order_reviews": "olist_order_reviews_dataset.csv",
    "raw_products": "olist_products_dataset.csv",
    "raw_category_translation": "product_category_name_translation.csv",
}

DATE_COLS = {
    "raw_orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "raw_order_items": ["shipping_limit_date"],
    "raw_order_reviews": ["review_creation_date", "review_answer_timestamp"],
}


def load_all_csvs():
    for table, filename in FILES_MAP.items():
        filepath = os.path.join(RAW_DIR, filename)
        print(f"Reading {filename}...")
        df = pd.read_csv(filepath, encoding="utf-8")

        # Parse dates cleanly so blanks become SQL NULL
        for col in DATE_COLS.get(table, []):
            df[col] = pd.to_datetime(df[col], errors="coerce")

        # Clean empty or literal 'NULL' strings in review text
        if table == "raw_order_reviews":
            for col in ["review_comment_title", "review_comment_message"]:
                df[col] = df[col].where(df[col].notna(), None)
                df[col] = df[col].apply(
                    lambda x: x.strip()
                    if isinstance(x, str) and x.strip() not in ("", "NULL", "null", "nan")
                    else None
                )

        # Clear existing rows so the script is safely re-runnable
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {table};"))

        # Load data into MySQL in chunks
        df.to_sql(table, con=engine, if_exists="append", index=False, chunksize=5000)
        print(f"  -> Loaded {len(df):,} rows into {table}")

    print("\nSUCCESS: All 7 tables populated in MySQL!")


if __name__ == "__main__":
    load_all_csvs()