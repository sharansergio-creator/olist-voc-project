import os
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

VIEWS_TO_EXPORT = [
    "vw_pbi_orders",
    "vw_pbi_voc_weighted",
    "vw_pbi_cohort_retention",
]

def export_views():
    os.makedirs("data/processed", exist_ok=True)
    for view_name in VIEWS_TO_EXPORT:
        print(f"Exporting {view_name}...")
        df = pd.read_sql(text(f"SELECT * FROM {view_name}"), engine)
        out_path = os.path.join("data", "processed", f"{view_name}.csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  -> Saved {len(df):,} rows to {out_path}")
    print("\nSUCCESS: All 3 Power BI datasets exported!")

if __name__ == "__main__":
    export_views()