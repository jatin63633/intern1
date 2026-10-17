"""Readmission-risk classifier: candidate comparison, persistence, scoring and per-patient explanations."""
import os
from datetime import datetime, timezone
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

NUM = ["age", "los", "prior_adm_180", "prior_adm_total", "days_since_last",
       "temperature", "systolic", "diastolic", "pulse", "sugar"]
CAT = ["gender", "department", "diagnosis"]
FEATURES = NUM + CAT
FRIENDLY = {"age": "Age", "los": "Length of stay (days)", "prior_adm_180": "Admissions in prior 180 days",
            "prior_adm_total": "Total prior admissions", "days_since_last": "Days since previous discharge",
            "temperature": "Temperature (C)", "systolic": "Systolic BP", "diastolic": "Diastolic BP",
            "pulse": "Pulse", "sugar": "Blood sugar (mg/dL)"}
MODEL_FILE = "readmission_best.joblib"


def _preprocessor():
    return ColumnTransformer([
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CAT)])


def _candidates(pos_weight):
    c = {"Logistic Regression": LogisticRegression(max_iter=2000, class_weight="balanced"),
         "Random Forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced_subsample",
                                                 random_state=42, n_jobs=-1),
         "Gradient Boosting": GradientBoostingClassifier(random_state=42)}
    try:                                       # optional dependency
        from xgboost import XGBClassifier
        c["XGBoost"] = XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.08, scale_pos_weight=pos_weight,
                                     eval_metric="logloss", random_state=42, verbosity=0)
    except Exception:
        pass
    return c


def _pipe(clf):
    return Pipeline([("pre", _preprocessor()), ("clf", clf)])


def train(feats, model_dir, high, medium):
    lab = feats.dropna(subset=["label"])
    y = lab["label"].astype(int).reset_index(drop=True)
    if len(lab) < 100 or y.sum() < 15 or (y == 0).sum() < 15:
        raise ValueError(f"Need at least 100 labelled discharges with 15+ readmissions and 15+ non-readmissions "
                         f"(found {len(lab)} labelled, {int(y.sum())} readmitted).")
    X, groups = lab[FEATURES].reset_index(drop=True), lab["patient_id"].reset_index(drop=True)
    for seed in range(42, 60):                 # split by PATIENT so the same person is never in train and test
        tr, te = next(GroupShuffleSplit(1, test_size=0.25, random_state=seed).split(X, y, groups))
        if y.iloc[tr].sum() >= 5 and y.iloc[te].sum() >= 5 and (y.iloc[te] == 0).sum() >= 5:
            break
    else:
        raise ValueError("Could not build a usable train/test split.")
    pos_weight = float((y.iloc[tr] == 0).sum() / max(1, (y.iloc[tr] == 1).sum()))

    rows = []
    for name, clf in _candidates(pos_weight).items():
        fit_kw = {"clf__sample_weight": compute_sample_weight("balanced", y.iloc[tr])} if name == "Gradient Boosting" else {}
        p = _pipe(clf).fit(X.iloc[tr], y.iloc[tr], **fit_kw)
        proba = p.predict_proba(X.iloc[te])[:, 1]
        pred = (proba >= 0.5).astype(int)
        tn, fp, fn, tp = confusion_matrix(y.iloc[te], pred, labels=[0, 1]).ravel()
        rows.append({"model": name, "accuracy": round(accuracy_score(y.iloc[te], pred), 3),
                     "precision": round(precision_score(y.iloc[te], pred, zero_division=0), 3),
                     "recall": round(recall_score(y.iloc[te], pred, zero_division=0), 3),
                     "f1": round(f1_score(y.iloc[te], pred, zero_division=0), 3),
                     "roc_auc": round(roc_auc_score(y.iloc[te], proba), 3),
                     "cm": [[int(tn), int(fp)], [int(fn), int(tp)]]})
    best = max(rows, key=lambda r: (r["f1"], r["roc_auc"]))
    for r in rows:
        r["best"] = r is best
    final = _pipe(_candidates(pos_weight)[best["model"]])
    kw = {"clf__sample_weight": compute_sample_weight("balanced", y)} if best["model"] == "Gradient Boosting" else {}
    final.fit(X, y, **kw)                     # refit the winner on all labelled data
    bundle = {"pipeline": final, "name": best["model"], "best": best, "comparison": rows,
              "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
              "n_train": int(len(tr)), "n_test": int(len(te)), "n_total": int(len(lab)),
              "readmit_rate": round(float(y.mean()) * 100, 1),
              "medians": {c: float(lab[c].median()) for c in NUM},
              "high": high, "medium": medium}
    os.makedirs(model_dir, exist_ok=True)
    joblib.dump(bundle, os.path.join(model_dir, MODEL_FILE))
    return bundle


def load(model_dir):
    path = os.path.join(model_dir, MODEL_FILE)
    return joblib.load(path) if os.path.exists(path) else None


def level(score, bundle):
    return "High" if score >= bundle["high"] else "Medium" if score >= bundle["medium"] else "Low"


def score(bundle, df):
    return bundle["pipeline"].predict_proba(df[FEATURES])[:, 1]


def explain(bundle, row_df, top=4):
    """What-if attribution: how much does the risk drop if one numeric feature is set to the cohort median?"""
    pipe, med = bundle["pipeline"], bundle["medians"]
    base = float(pipe.predict_proba(row_df[FEATURES])[0, 1])
    out = []
    for f in NUM:
        val = row_df.iloc[0][f]
        if pd.isna(val):
            continue
        alt = row_df.copy()
        alt[f] = med[f]
        delta = base - float(pipe.predict_proba(alt[FEATURES])[0, 1])
        if abs(delta) >= 0.01:
            out.append({"feature": FRIENDLY[f], "value": round(float(val), 1), "typical": round(med[f], 1),
                        "effect": round(delta * 100, 1)})
    return sorted(out, key=lambda r: -abs(r["effect"]))[:top]
