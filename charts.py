"""Step 4: charts.

    ./venv/bin/python charts.py   -> charts/01_star_schema.png (Graphviz), 02_one_hospital.png, 03_releases.png,
                                     04_ownership.png, 05_reh.png
"""
import shutil
import subprocess
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import warehouse as W

HERE = Path(__file__).parent
R = HERE / "results"
INK, DIM, GRID, BG, BLUE, ORANGE, GRAY = "#f2f2f0", "#8a8a87", "#1d1d1d", "#0b0b0b", "#3987e5", "#d95926", "#9a9a96"
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG, "text.color": INK,
    "axes.edgecolor": "#3a3a3a", "axes.labelcolor": DIM, "xtick.color": DIM, "ytick.color": DIM,
    "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 1,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 11, "axes.titlesize": 13,
    "axes.titlelocation": "left", "axes.titlepad": 12,
})
DOT = shutil.which("dot") or str(Path.home() / "micromamba" / "envs" / "analyst" / "bin" / "dot")


def save(fig, name):
    fig.tight_layout()
    fig.savefig(HERE / "charts" / name, dpi=150)
    plt.close(fig)


def star_schema(con):
    cols = con.execute("""SELECT table_name, column_name, data_type FROM information_schema.columns
                           WHERE table_name IN ('fact_rating', 'dim_hospital', 'dim_date', 'hospital_lineage') ORDER BY table_name, ordinal_position""").fetchall()
    tables = {}
    for t, c, typ in cols:
        tables.setdefault(t, []).append((c, typ.lower().replace("character varying", "varchar")))
    notes = {"hospital_sk": "surrogate key", "hospital_key": "durable key", "facility_id": "business key (CMS ID)",
             "ownership": "Type 2", "hospital_type": "Type 2", "emergency_services": "Type 2", "name": "Type 1",
             "valid_from": "SCD dates", "valid_to": "SCD dates"}
    note = lambda t, c: f'<font color="#d9a35f">{notes[c]}</font>' if t == "dim_hospital" and c in notes else " "
    lines = ['digraph S {', '  graph [bgcolor="#0b0b0b", rankdir=LR, nodesep=0.5, ranksep=1.1];',
             '  node [shape=plaintext, fontname="Helvetica", fontcolor="#f2f2f0"];',
             '  edge [color="#8a8a87", fontname="Helvetica", fontsize=10, fontcolor="#8a8a87", arrowhead=none];']
    head = {"fact_rating": "#4a2414", "dim_hospital": "#1f3b5c", "dim_date": "#1f3b5c", "hospital_lineage": "#2a2a2a"}
    for t, cs in tables.items():
        rows = "".join(f'<tr><td align="left" port="{c}_w">{c}</td><td align="left"><font color="#8a8a87">{typ}</font></td>'
                       f'<td align="left" port="{c}_e">{note(t, c)}</td></tr>' for c, typ in cs)
        lines.append(f'  {t} [label=<<table border="1" cellborder="0" cellspacing="0" cellpadding="3" color="#3a3a3a" bgcolor="#141414">'
                     f'<tr><td colspan="3" bgcolor="{head[t]}"><b>{t}</b></td></tr>{rows}</table>>];')
    lines += ['  dim_date:date_key_e:e -> fact_rating:date_key_w:w;', '  fact_rating:hospital_sk_e:e -> dim_hospital:hospital_sk_w:w;',
              '  dim_hospital:facility_id_e:e -> hospital_lineage:old_facility_id_w:w [style=dashed, label="ID changes"];', '}']
    dot = HERE / "charts" / "star_schema.dot"
    dot.write_text("\n".join(lines) + "\n")
    subprocess.run([DOT, "-Tpng", "-Gdpi=130", str(dot), "-o", str(HERE / "charts" / "01_star_schema.png")], check=True)


def main():
    (HERE / "charts").mkdir(exist_ok=True)
    con = duckdb.connect(str(W.DB), read_only=True)
    star_schema(con)

    v = con.execute("""SELECT hospital_sk, facility_id, hospital_type, ownership, emergency_services, valid_from, valid_to, change_reason
                         FROM dim_hospital WHERE hospital_key = (SELECT hospital_key FROM dim_hospital WHERE name LIKE 'IRA DAVENPORT%' LIMIT 1)
                        ORDER BY valid_from""").df()
    f = con.execute("""SELECT f.date_key, f.overall_rating FROM fact_rating f JOIN dim_hospital h USING (hospital_sk)
                        WHERE h.name LIKE 'IRA DAVENPORT%' ORDER BY 1""").df()
    end = pd.Timestamp(con.execute("SELECT max(date_key) FROM dim_date").fetchone()[0]) + pd.Timedelta(days=60)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for i, r in v.iterrows():
        start, stop = pd.Timestamp(r["valid_from"]), (pd.Timestamp(r["valid_to"]) if pd.notna(r["valid_to"]) else end)
        color = ORANGE if r["hospital_type"] == "Rural Emergency Hospital" else BLUE
        ax.barh(i, (stop - start).days, left=start, color=color, height=0.55, alpha=0.9)
        er = "ER" if r["emergency_services"] else "no ER"
        kind = {"Acute Care Hospitals": "acute care", "Rural Emergency Hospital": "rural emergency"}.get(r["hospital_type"], r["hospital_type"])
        own = r["ownership"].replace("Voluntary non-profit - ", "non-profit, ").lower()
        ax.text(start + pd.Timedelta(days=15), i, f"v{i + 1} · ID {r['facility_id']} · {kind} · {own} · {er}", va="center", color=INK, fontsize=8.5)
        ax.text(start, i - 0.42, r["change_reason"], color=DIM, fontsize=8)
    ax.set_xlim(pd.Timestamp(v["valid_from"].min()) - pd.Timedelta(days=30), end + pd.Timedelta(days=420))
    ax.set_yticks([])
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_title("One hospital in dim_hospital: Ira Davenport Memorial (NY), five versions, two facility IDs")
    ax.set_xlabel("each bar is one version, valid_from to valid_to; orange = Rural Emergency Hospital")
    save(fig, "02_one_hospital.png")

    a = pd.read_csv(R / "etl_audit.csv", parse_dates=["date_key"])
    fig, ax = plt.subplots(figsize=(10, 4.0))
    x = np.arange(len(a))
    ax.bar(x - 0.27, a["new_hospitals"], width=0.27, color=BLUE, label="new hospitals")
    ax.bar(x, a["new_versions"], width=0.27, color=ORANGE, label="new Type 2 versions")
    ax.bar(x + 0.27, a["closed"], width=0.27, color=GRAY, label="left the data")
    ax.set_yscale("symlog", linthresh=10)
    ax.set_xticks(x, a["date_key"].dt.strftime("%y-%m"), rotation=60, fontsize=8)
    for idx, txt in [(a.index[a["date_key"] == "2019-07-31"][0], "psychiatric\nhospitals added"),
                     (a.index[a["date_key"] == "2023-07-06"][0], "VA hospitals\nadded")]:
        ax.annotate(txt, (idx - 0.27, a.loc[idx, "new_hospitals"]), xytext=(idx + 1.5, 900), color=DIM, fontsize=8,
                    arrowprops=dict(arrowstyle="-", color=DIM))
    ax.set_ylabel("rows (log scale above 10)")
    ax.legend(frameon=False, labelcolor=INK, fontsize=9, loc="upper right", ncol=3)
    ax.grid(axis="x", visible=False)
    ax.set_title("The ETL audit, release by release (first release: 4,784 hospitals loaded)")
    save(fig, "03_releases.png")

    t = pd.read_csv(R / "ownership_transitions.csv")
    groups = ["Non-profit", "For-profit", "Government"]
    m = t.pivot_table(index="ownership_2019", columns="ownership_2026", values="hospitals", aggfunc="sum").reindex(index=groups, columns=groups).fillna(0)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    off = m.values.copy().astype(float)
    np.fill_diagonal(off, np.nan)
    ax.imshow(np.log1p(np.nan_to_num(off)), cmap="Blues", vmin=0, vmax=np.log1p(np.nanmax(off) * 1.4))
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{int(m.values[i, j]):,}", ha="center", va="center", color=INK if i != j else DIM, fontsize=12)
    ax.set_xticks(range(3), groups)
    ax.set_yticks(range(3), groups)
    ax.set_xlabel("ownership in August 2026")
    ax.set_ylabel("ownership in March 2019")
    ax.grid(False)
    ax.set_title("Hospitals in both releases: who changed ownership group")
    save(fig, "04_ownership.png")

    h = pd.read_csv(R / "hospitals_by_release.csv", parse_dates=["date_key"])
    r = pd.read_csv(R / "rural_emergency_hospitals.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1.6, 1]})
    axes[0].plot(h["date_key"], h["rural_emergency"], color=ORANGE, linewidth=2, marker="o", markersize=4)
    axes[0].set_title("Rural Emergency Hospitals listed by CMS", fontsize=12)
    axes[0].set_ylabel("hospitals")
    prev = r["previous_type"].fillna("no earlier ID found").value_counts()
    axes[1].barh(prev.index[::-1], prev.values[::-1], color=[GRAY if "no" in i else BLUE for i in prev.index[::-1]], height=0.6)
    for i, v in enumerate(prev.values[::-1]):
        axes[1].text(v + 0.4, i, str(v), va="center", color=INK, fontsize=10)
    axes[1].set_title("What they were before (via lineage)", fontsize=12)
    axes[1].grid(axis="y", visible=False)
    fig.suptitle("A new kind of hospital: rural hospitals that stop inpatient care and keep the emergency room",
                 x=0.01, ha="left", fontsize=13, color=INK)
    save(fig, "05_reh.png")
    print("charts written")


if __name__ == "__main__":
    main()
