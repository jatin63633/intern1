CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin','doctor','staff'))
);

CREATE TABLE IF NOT EXISTS patients (
    patient_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    age         INTEGER NOT NULL CHECK (age BETWEEN 0 AND 120),
    gender      TEXT NOT NULL CHECK (gender IN ('Male','Female','Other')),
    phone       TEXT,
    blood_group TEXT NOT NULL DEFAULT 'Unknown'
);

CREATE TABLE IF NOT EXISTS admissions (
    admission_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    admission_date TEXT NOT NULL,                 -- YYYY-MM-DD
    discharge_date TEXT,                          -- NULL = currently admitted
    diagnosis      TEXT NOT NULL,
    department     TEXT NOT NULL,
    CHECK (discharge_date IS NULL OR discharge_date >= admission_date)
);
CREATE INDEX IF NOT EXISTS idx_adm_patient ON admissions(patient_id, admission_date);

CREATE TABLE IF NOT EXISTS vitals (
    vital_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    temperature REAL,                             -- deg C
    bp          TEXT,                             -- 'systolic/diastolic', e.g. 120/80
    pulse       INTEGER,                          -- beats/min
    sugar       REAL,                             -- blood glucose, mg/dL
    recorded_at TEXT NOT NULL                     -- YYYY-MM-DD HH:MM:SS
);
CREATE INDEX IF NOT EXISTS idx_vitals_patient ON vitals(patient_id, recorded_at);

-- One row per scored patient per run. run_id/model_name/created_by/predicted_at form the audit trail.
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    admission_id  INTEGER REFERENCES admissions(admission_id) ON DELETE CASCADE,
    risk_score    REAL NOT NULL CHECK (risk_score BETWEEN 0 AND 1),
    risk_level    TEXT NOT NULL CHECK (risk_level IN ('Low','Medium','High')),
    predicted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    run_id        TEXT NOT NULL,
    model_name    TEXT NOT NULL,
    run_type      TEXT NOT NULL DEFAULT 'batch' CHECK (run_type IN ('batch','single')),
    created_by    INTEGER REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_pred_run ON predictions(run_id);
CREATE INDEX IF NOT EXISTS idx_pred_patient ON predictions(patient_id, predicted_at);
