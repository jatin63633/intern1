# MediIQ - Hospital Patient Analytics & Readmission Risk Prediction (Project 3)

Flask + Pandas + scikit-learn (+ optional XGBoost) + Jinja + Chart.js, SQLite storage.
**Academic decision-support prototype using synthetic data - not a clinical diagnostic system.**

## Run
    pip install -r requirements.txt
    python seed_data.py      # synthetic demo data: 1,500 patients, ~2,100 admissions, vitals
    python app.py            # http://127.0.0.1:5000
Logins: `admin/admin12345`, `doctor1/doctor12345`, `staff1/staff12345`. Then open **Prediction -> Train models -> Score patients**.
Set `SECRET_KEY` in the environment for anything beyond a demo. Delete `instance/` and `models/` to reset.

## Layers
| Layer | Files |
|---|---|
| Presentation | `views.py`, `auth.py`, `templates/`, `static/` |
| Business logic | `services/features.py` (label + features), `analytics.py` (Pandas), `model.py` (ML), `validation.py`, `ingest.py` |
| Database access | `db.py` (connection), `repo.py` (all SQL), `schema.sql` |

## ML design
- Label: readmitted within 30 days of discharge. Admissions still open, or without a complete 30-day follow-up window, are excluded from training (censoring) but can be scored.
- Features use only information available at discharge: age, gender, department, diagnosis, length of stay, prior admissions (180 days / total), days since previous discharge, last vitals during the stay.
- Split by patient (GroupShuffleSplit) so no patient is in both train and test. Numeric: median impute + scale; categorical: one-hot.
- Candidates: Logistic Regression, Random Forest, Gradient Boosting, XGBoost if installed. Metrics: accuracy, precision, recall, F1, ROC-AUC, confusion matrix. Best by F1 (ROC-AUC tie-break) is refit on all labelled data and saved to `models/`.
- Risk levels: High >= 0.60, Medium >= 0.35 (`config.py`).

## Roles
`admin` everything (delete records, manage users) - the first registered account; `doctor` records + Doctor dashboard + training/scoring; `staff` registration, data entry, analytics. New sign-ups are `staff`.

## Notes
- `predictions` adds `admission_id, run_id, model_name, run_type, created_by` to the spec columns for audit; `predicted_at` is stored in UTC.
- Synthetic readmission patterns are programmed into the demo data, so reported metrics describe the demo, not real hospitals.
