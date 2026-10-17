"""Turns admissions + vitals into one modelling row per admission, with a 30-day readmission label."""
import re
import numpy as np
import pandas as pd

READMIT_DAYS = 30
VITAL_COLS = ["temperature", "systolic", "diastolic", "pulse", "sugar"]


def parse_bp(s):
    m = re.fullmatch(r"\s*(\d{2,3})\s*/\s*(\d{2,3})\s*", s or "") if isinstance(s, str) else None
    return (float(m[1]), float(m[2])) if m else (np.nan, np.nan)


def build_frame(adm, vit, as_of=None):
    """One row per admission.
    label = 1 if the patient was admitted again within 30 days of discharge, 0 if not, NaN if
    still admitted or the 30-day follow-up window is not yet complete (censored).
    Every feature uses only information available at discharge (no look-ahead leakage)."""
    if adm.empty:
        return pd.DataFrame()
    a = adm.sort_values(["patient_id", "admission_date", "admission_id"]).reset_index(drop=True).copy()
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.today().normalize()
    seen = [a["admission_date"].max()] + ([a["discharge_date"].max()] if a["discharge_date"].notna().any() else [])
    data_end = max(seen)

    a["discharged"] = a["discharge_date"].notna()
    a["los"] = ((a["discharge_date"].fillna(as_of) - a["admission_date"]).dt.days).clip(lower=1)
    g = a.groupby("patient_id")
    a["prior_adm_total"] = g.cumcount()
    a["days_since_last"] = (a["admission_date"] - g["discharge_date"].shift(1)).dt.days.fillna(365).clip(0, 365)

    p180 = np.zeros(len(a), dtype=int)
    dates = a["admission_date"].to_numpy()
    for idx in g.indices.values():
        for k, i in enumerate(idx):
            p180[i] = int((dates[idx[:k]] >= dates[i] - np.timedelta64(180, "D")).sum())
    a["prior_adm_180"] = p180

    nxt = g["admission_date"].shift(-1)
    gap = (nxt - a["discharge_date"]).dt.days
    label = np.where(a["discharged"] & nxt.notna(), (gap <= READMIT_DAYS).astype(float), np.nan)
    followed_up = a["discharged"] & nxt.isna() & (a["discharge_date"] + pd.Timedelta(days=READMIT_DAYS) <= data_end)
    a["label"] = np.where(followed_up, 0.0, label)

    # latest vitals recorded during the stay (on/before discharge, or now if still admitted)
    for c in VITAL_COLS:
        a[c] = np.nan
    if not vit.empty:
        v = vit.copy()
        sd = v["bp"].apply(parse_bp)
        v["systolic"], v["diastolic"] = sd.str[0], sd.str[1]
        v["recorded_at"] = v["recorded_at"].astype("datetime64[ns]")
        v = v.sort_values("recorded_at")[["patient_id", "recorded_at"] + VITAL_COLS]
        left = a[["admission_id", "patient_id", "admission_date"]].copy()
        end = (a["discharge_date"] + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).fillna(as_of + pd.Timedelta(days=1))
        left["t"] = end.astype("datetime64[ns]")
        m = pd.merge_asof(left.sort_values("t"), v, left_on="t", right_on="recorded_at", by="patient_id", direction="backward")
        stale = m["recorded_at"] < m["admission_date"].astype("datetime64[ns]")
        m.loc[stale, VITAL_COLS] = np.nan
        a = a.drop(columns=VITAL_COLS).merge(m[["admission_id"] + VITAL_COLS], on="admission_id", how="left")
    return a
