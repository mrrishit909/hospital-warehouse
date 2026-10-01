"""Steps 2-3: build the warehouse release by release, as a quarterly ETL job would, then run the marts.

    ./venv/bin/python warehouse.py        -> data/warehouse.duckdb, results/*.csv

Each CMS release is staged, compared with the current dimension, and loaded (Type 1 overwrite, Type 2 new versions,
closures, returns, new hospitals), then its ratings are added to the fact table. A release already in dim_date is
skipped, so running the job twice changes nothing.
"""
import re
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
DB = HERE / "data" / "warehouse.duckdb"
SNAPS = HERE / "data" / "snapshots"
SQL = HERE / "sql"


def blocks(path):
    text = path.read_text()
    return [(m.group(1).strip(), m.group(2).strip().rstrip(";")) for m in re.finditer(r"-- name: ([^\n]+)\n(.*?)(?=\n-- name:|\Z)", text, re.S)]


def load_release(con, snap, file):
    if con.execute("SELECT count(*) FROM dim_date WHERE date_key = ?", [snap]).fetchone()[0]:
        return False                                                   # already loaded: idempotent
    n = con.execute("SELECT count(*) FROM dim_date").fetchone()[0]
    con.execute("INSERT INTO dim_date VALUES (?, year(CAST(? AS date)), quarter(CAST(? AS date)), ?)", [snap, snap, snap, n + 1])
    con.execute((SQL / "02_stage.sql").read_text().replace("{file}", str(file)))
    con.execute((SQL / "04_load.sql").read_text().replace("{snap}", snap))
    steps = dict(con.execute("SELECT step, n FROM audit_step").fetchall())
    con.execute("INSERT INTO etl_audit VALUES (?, (SELECT count(*) FROM stg), ?, ?, ?, ?, ?, ?)",
                [snap, steps["new_hospitals"], steps["new_versions"], steps["closed"], steps["reopened"], steps["type1"], steps["facts"]])
    return True


def build(fresh=True):
    if fresh and DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    if fresh:
        con.execute((SQL / "01_model.sql").read_text())
        con.execute((SQL / "03_lineage.sql").read_text().replace("{snapshots}", str(SNAPS)))
    for file in sorted(SNAPS.glob("general_*.csv")):
        load_release(con, file.stem.split("_")[1], file)
    return con


def main():
    con = build()
    (HERE / "results").mkdir(exist_ok=True)
    for name, sql in blocks(SQL / "05_marts.sql"):
        sql = sql.replace("{snapshots}", str(SNAPS))
        con.execute(f"COPY ({sql}) TO '{HERE / 'results' / (name + '.csv')}' (HEADER)")
    print(con.execute("SELECT * FROM etl_audit ORDER BY date_key").df().to_string(index=False))
    print(con.execute("SELECT change_reason, count(*) FROM dim_hospital GROUP BY 1 ORDER BY 2 DESC").fetchall())
    print(con.execute("SELECT count(*), count(DISTINCT hospital_key), sum(is_current::int) FROM dim_hospital").fetchall())


if __name__ == "__main__":
    main()
