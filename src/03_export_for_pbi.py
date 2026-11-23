import os
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

OUT_DIR = "data/processed"
os.makedirs(OUT_DIR, exist_ok=True)

VIEWS = [
    "vw_pbi_orders",
    "vw_pbi_voc_weighted",
    "vw_pbi_cohort_retention",
]

def export_views():
    for view in VIEWS:
        print(f"Exporting {view}...")
        df = pd.read_sql(text(f"SELECT * FROM {view}"), engine)
        out_path = os.path.join(OUT_DIR, f"{view}.csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  -> Saved {len(df):,} rows to {out_path}")

    print("\nSUCCESS: All 3 Power BI datasets exported!")

if __name__ == "__main__":
    export_views()