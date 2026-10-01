"""The project's check: run after warehouse.py. Fails loudly if the slowly changing dimension or the facts go wrong.

    ./venv/bin/python check.py

1. idempotent: running the job again over the same releases adds nothing
2. Type 2 integrity: at most one current version per hospital, versions never overlap, dates are consistent
3. every fact points at the version that was valid on its date; facts per release = hospitals in that raw file
4. replay: for 500 random (hospital, release) pairs, the warehouse's ownership/type/emergency-services as of that date
   equal the raw snapshot file; current names equal the latest file (Type 1)
"""
from pathlib import Path

import duckdb
import pandas as pd

import warehouse as W

HERE = Path(__file__).parent


def main():
    con = duckdb.connect(str(W.DB))
    counts = lambda: con.execute("SELECT (SELECT count(*) FROM dim_hospital), (SELECT count(*) FROM fact_rating), (SELECT count(*) FROM etl_audit)").fetchone()
    before = counts()
    for f in sorted(W.SNAPS.glob("general_*.csv")):
        assert not W.load_release(con, f.stem.split("_")[1], f), "a loaded release must be skipped"
    assert counts() == before

    q = lambda sql: con.execute(sql).fetchone()[0]
    assert q("SELECT count(*) FROM (SELECT hospital_key FROM dim_hospital WHERE is_current GROUP BY 1 HAVING count(*) > 1)") == 0
    assert q("SELECT count(*) FROM dim_hospital WHERE is_current <> (valid_to IS NULL)") == 0
    assert q("SELECT count(*) FROM dim_hospital WHERE valid_to <= valid_from") == 0
    assert q("""SELECT count(*) FROM dim_hospital a JOIN dim_hospital b ON a.hospital_key = b.hospital_key AND a.hospital_sk < b.hospital_sk
                 WHERE a.valid_from < coalesce(b.valid_to, DATE '9999-12-31') AND b.valid_from < coalesce(a.valid_to, DATE '9999-12-31')""") == 0
    assert q("""SELECT count(*) FROM fact_rating f JOIN dim_hospital h USING (hospital_sk)
                 WHERE NOT (h.valid_from <= f.date_key AND f.date_key < coalesce(h.valid_to, DATE '9999-12-31'))""") == 0

    raw = []
    for f in sorted(W.SNAPS.glob("general_*.csv")):
        d = pd.read_csv(f, dtype=str, keep_default_na=False).drop_duplicates("facility_id")
        d["date_key"] = f.stem.split("_")[1]
        raw.append(d)
    raw = pd.concat(raw, ignore_index=True)
    facts = con.execute("SELECT strftime(date_key, '%Y-%m-%d') AS d, count(*) AS n FROM fact_rating GROUP BY 1").df().set_index("d")["n"]
    assert (raw.groupby("date_key").size() == facts.reindex(raw["date_key"].unique())).all()

    sample = raw.sample(500, random_state=4)
    got = con.execute("""SELECT f.date_key, h.facility_id, h.ownership, h.hospital_type, h.emergency_services
                           FROM fact_rating f JOIN dim_hospital h USING (hospital_sk)""").df()
    got["date_key"] = got["date_key"].astype(str).str[:10]
    m = sample.merge(got, on=["date_key", "facility_id"], suffixes=("_raw", ""))
    assert len(m) == len(sample)
    norm = lambda s: s.str.strip().replace({"": "Not Available"})
    assert (norm(m["ownership_raw"]) == m["ownership"]).all()
    assert (norm(m["hospital_type_raw"]) == m["hospital_type"]).all()
    assert (m["emergency_services_raw"].str.strip().str.upper().map({"YES": True, "NO": False}) == m["emergency_services"]).all()

    last = raw[raw["date_key"] == raw["date_key"].max()].set_index("facility_id")["name"]
    cur = con.execute("SELECT facility_id, name FROM dim_hospital WHERE is_current").df().set_index("facility_id")["name"]
    clean = last.str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    assert (cur.reindex(clean.index) == clean).all()

    reh = q("SELECT count(DISTINCT facility_id) FROM dim_hospital WHERE hospital_type = 'Rural Emergency Hospital'")
    assert reh == raw.loc[raw["hospital_type"] == "Rural Emergency Hospital", "facility_id"].nunique()
    print(f"OK: rerun adds nothing; {before[0]:,} versions with no overlaps and one current version per hospital; "
          f"{before[1]:,} facts each on the version valid that day and matching every raw file's count; 500 sampled "
          f"(hospital, release) pairs replay the raw files exactly; Type 1 names current; {reh} Rural Emergency Hospitals")


if __name__ == "__main__":
    main()
