"""Descriptive + diagnostic analytics with Pandas (no SQL, no Flask)."""
import numpy as np
import pandas as pd

AGE_BINS = [-1, 17, 39, 59, 79, 200]
AGE_LABELS = ["0-17", "18-39", "40-59", "60-79", "80+"]


def filter_adm(adm, dept=None, start=None, end=None):
    if dept:
        adm = adm[adm["department"] == dept]
    if start:
        adm = adm[adm["admission_date"] >= pd.to_datetime(start)]
    if end:
        adm = adm[adm["admission_date"] <= pd.to_datetime(end)]
    return adm


def _feats_for(adm, feats):
    return feats[feats["admission_id"].isin(adm["admission_id"])] if not feats.empty else feats


def _num(x, nd=1):
    return None if pd.isna(x) else round(float(x), nd)


# ---------- descriptive ----------
def kpis(adm, feats):
    if adm.empty:
        return None
    f = _feats_for(adm, feats)
    done = f[f["discharged"]]
    lab = f.dropna(subset=["label"])
    return {"patients": int(adm["patient_id"].nunique()), "admissions": int(len(adm)),
            "inpatients": int(adm["discharge_date"].isna().sum()),
            "avg_los": _num(done["los"].mean(), 2) if len(done) else None,
            "readmit_rate": _num(lab["label"].mean() * 100) if len(lab) else None,
            "top_dx": adm["diagnosis"].value_counts().index[0]}


def diagnosis_distribution(adm, top=10):
    vc = adm["diagnosis"].value_counts().head(top)
    return {"labels": vc.index.tolist(), "values": [int(v) for v in vc.values]}


def los_by_department(feats):
    d = feats[feats["discharged"]].groupby("department")["los"].mean().sort_values(ascending=False)
    return {"labels": d.index.tolist(), "values": [round(float(v), 2) for v in d.values]}


def los_histogram(feats):
    d = feats[feats["discharged"]]["los"]
    bins, labels = [0, 2, 4, 6, 8, 10, 14, 21, 1000], ["1-2", "3-4", "5-6", "7-8", "9-10", "11-14", "15-21", "22+"]
    vc = pd.cut(d, bins=bins, labels=labels).value_counts().reindex(labels).fillna(0)
    return {"labels": labels, "values": [int(v) for v in vc.values]}


def admissions_trend(adm):
    s = adm.groupby(adm["admission_date"].dt.to_period("M")).size()
    return {"labels": [str(p) for p in s.index], "values": [int(v) for v in s.values]}


def age_gender(adm):
    p = adm.drop_duplicates("patient_id")
    ages = pd.cut(p["age"], bins=AGE_BINS, labels=AGE_LABELS).value_counts().reindex(AGE_LABELS).fillna(0)
    return {"labels": AGE_LABELS, "values": [int(v) for v in ages.values],
            "gender": {k: int(v) for k, v in p["gender"].value_counts().items()}}


# ---------- occupancy ----------
def census(adm, as_of=None):
    """Daily bed census per department (a patient occupies a bed from admission day until the day before discharge)."""
    if adm.empty:
        return pd.DataFrame()
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.today().normalize()
    end_all = max(as_of, adm["admission_date"].max())
    days = pd.date_range(adm["admission_date"].min(), end_all, freq="D")
    out = {}
    for dept, g in adm.groupby("department"):
        leave = g["discharge_date"].fillna(end_all + pd.Timedelta(days=1))
        leave = np.maximum(leave, g["admission_date"] + pd.Timedelta(days=1))
        delta = (g["admission_date"].value_counts().reindex(days, fill_value=0)
                 - pd.Series(leave).value_counts().reindex(days, fill_value=0))
        out[dept] = delta.cumsum()
    return pd.DataFrame(out, index=days)


def occupancy_monthly(adm):
    c = census(adm)
    if c.empty:
        return {"labels": [], "datasets": []}
    m = c.resample("MS").mean().round(1)
    return {"labels": [d.strftime("%Y-%m") for d in m.index],
            "datasets": [{"label": col, "data": [float(v) for v in m[col]]} for col in m.columns]}


def department_stats(adm, feats):
    if adm.empty:
        return []
    f, c = _feats_for(adm, feats), census(adm)
    rows = []
    for dept, g in adm.groupby("department"):
        fd = f[f["department"] == dept]
        done, lab = fd[fd["discharged"]], fd.dropna(subset=["label"])
        rows.append({"department": dept, "admissions": int(len(g)), "inpatients": int(g["discharge_date"].isna().sum()),
                     "avg_los": _num(done["los"].mean(), 2) if len(done) else None,
                     "avg_census": _num(c[dept].mean()) if dept in c else None,
                     "readmit_rate": _num(lab["label"].mean() * 100) if len(lab) else None})
    return sorted(rows, key=lambda r: -r["admissions"])


# ---------- diagnostic ----------
def readmit_by(feats, col, min_n=8, bins=None, labels=None):
    lab = feats.dropna(subset=["label"]).copy()
    if lab.empty:
        return {"labels": [], "values": [], "n": []}
    key = pd.cut(lab[col], bins=bins, labels=labels) if bins is not None else lab[col]
    g = lab.groupby(key, observed=True)["label"].agg(["mean", "count"])
    g = g[g["count"] >= min_n].sort_values("mean", ascending=False)
    return {"labels": [str(i) for i in g.index], "values": [round(float(v) * 100, 1) for v in g["mean"]],
            "n": [int(v) for v in g["count"]]}


def diagnostic_insights(feats):
    lab = feats.dropna(subset=["label"])
    if len(lab) < 50:
        return ["Not enough completed follow-up data yet (need 50+ discharges with a full 30-day window)."]
    base, out = lab["label"].mean() * 100, []
    out.append(f"Overall 30-day readmission rate is {base:.1f}% across {len(lab)} discharges.")
    dx = readmit_by(feats, "diagnosis")
    if dx["labels"]:
        out.append(f"Highest-risk diagnosis: {dx['labels'][0]} ({dx['values'][0]}% readmitted, n={dx['n'][0]}); "
                   f"lowest: {dx['labels'][-1]} ({dx['values'][-1]}%).")
    hi, lo = lab[lab["prior_adm_180"] >= 2], lab[lab["prior_adm_180"] == 0]
    if len(hi) >= 8 and len(lo) >= 8:
        out.append(f"Patients with 2+ admissions in the prior 180 days were readmitted {hi['label'].mean() * 100:.1f}% "
                   f"of the time vs {lo['label'].mean() * 100:.1f}% for patients with none.")
    old, young = lab[lab["age"] >= 65], lab[lab["age"] < 65]
    if len(old) >= 8 and len(young) >= 8:
        out.append(f"Age 65+: {old['label'].mean() * 100:.1f}% readmitted vs {young['label'].mean() * 100:.1f}% under 65.")
    sug = lab.dropna(subset=["sugar"])
    hi, lo = sug[sug["sugar"] >= 180], sug[sug["sugar"] < 180]
    if len(hi) >= 8 and len(lo) >= 8:
        out.append(f"Discharge blood sugar >=180 mg/dL: {hi['label'].mean() * 100:.1f}% readmitted vs {lo['label'].mean() * 100:.1f}% below.")
    short, long_ = lab[lab["los"] <= 2], lab[lab["los"] >= 8]
    if len(short) >= 8 and len(long_) >= 8:
        out.append(f"Stays of 2 days or less: {short['label'].mean() * 100:.1f}% readmitted; stays of 8+ days: {long_['label'].mean() * 100:.1f}%.")
    out.append("These are associations in historical data, not proof of cause.")
    return out


# ---------- inpatients / vital flags ----------
def vital_flags(row):
    f = []
    if row.get("temperature") >= 38.0: f.append("Fever")
    if row.get("pulse") > 110: f.append("Tachycardia")
    if row.get("pulse") < 50: f.append("Bradycardia")
    if row.get("systolic") >= 160: f.append("High BP")
    if row.get("systolic") <= 90: f.append("Low BP")
    if row.get("sugar") >= 180: f.append("High glucose")
    if row.get("sugar") <= 70: f.append("Low glucose")
    return f


def inpatient_status(feats, dept=None):
    cur = feats[~feats["discharged"]]
    if dept:
        cur = cur[cur["department"] == dept]
    rows = []
    for r in cur.sort_values("admission_date").to_dict("records"):
        r = {k: (np.nan if v is None else v) for k, v in r.items()}
        rows.append({"patient_id": int(r["patient_id"]), "name": r["name"], "department": r["department"],
                     "diagnosis": r["diagnosis"], "admitted": r["admission_date"].strftime("%Y-%m-%d"),
                     "days": int(r["los"]), "flags": vital_flags(r),
                     "temperature": _num(r["temperature"]), "bp": None if pd.isna(r["systolic"]) else f"{int(r['systolic'])}/{int(r['diastolic'])}",
                     "pulse": _num(r["pulse"], 0), "sugar": _num(r["sugar"], 0)})
    return rows
