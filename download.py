"""Step 1: every quarterly snapshot of CMS's Hospital General Information, March 2019 to August 2026.

    ./venv/bin/python download.py

Source: CMS Provider Data Catalog, hospitals data archive (https://data.cms.gov/provider-data/archived-data/hospitals),
listed by the catalog's archive API. Each snapshot zip holds every hospital dataset; only the General Information file is
kept, with its columns mapped to one set of names (CMS renamed several, e.g. "Provider ID" -> "Facility ID").
Zips go to data/raw/ and extracted CSVs to data/snapshots/ (not committed).
"""
import io
import json
import ssl
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
API = "https://data.cms.gov/provider-data/api/1/archive/aggregate/theme/hospitals/relative"
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
COLUMNS = {  # old or new name -> warehouse name
    "Provider ID": "facility_id", "Facility ID": "facility_id", "Hospital Name": "name", "Facility Name": "name",
    "Address": "address", "City": "city", "City/Town": "city", "State": "state", "ZIP Code": "zip", "County Name": "county",
    "County/Parish": "county", "Hospital Type": "hospital_type", "Hospital Ownership": "ownership",
    "Emergency Services": "emergency_services", "Hospital overall rating": "overall_rating",
    "Hospital overall rating footnote": "rating_footnote",
}


def snapshots():
    data = json.load(urllib.request.urlopen(API, context=CTX, timeout=60))["data"]
    return sorted((x["date"], "https://data.cms.gov" + x["url"].replace("\\/", "/")) for x in data if x["type"] == "theme")


if __name__ == "__main__":
    (HERE / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (HERE / "data" / "snapshots").mkdir(parents=True, exist_ok=True)
    for date, url in snapshots():
        z = HERE / "data" / "raw" / f"hospitals_{date}.zip"
        if not z.exists():
            z.write_bytes(urllib.request.urlopen(url, context=CTX, timeout=600).read())
        with zipfile.ZipFile(z) as zf:
            # by name, or by the dataset's ID (xubh-q36u), which is all the 2020 files are called
            names = [n for n in zf.namelist() if ("general" in n.lower() or "xubh" in n.lower())
                     and n.lower().endswith(".csv") and "__macosx" not in n.lower()]
            if len(names) != 1:             # e.g. 2026-09-30: a partial update without this dataset
                print(date, "SKIPPED: general-information files found:", names)
                continue
            d = pd.read_csv(io.BytesIO(zf.read(names[0])), dtype=str, keep_default_na=False, encoding="latin1")
        d = d.rename(columns=COLUMNS)[sorted(set(COLUMNS.values()))]
        d.to_csv(HERE / "data" / "snapshots" / f"general_{date}.csv", index=False)
        print(date, len(d), "hospitals")
