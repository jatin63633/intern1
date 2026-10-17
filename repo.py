"""Repository functions: all SQL lives here (database access layer, part 2)."""
import pandas as pd
from db import get_db


def _q(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def _exec(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid


# ---------- users ----------
def count_users():
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username, password_hash, role):
    _exec("INSERT INTO users (username,password_hash,role) VALUES (?,?,?)", (username, password_hash, role))


def get_user_by_name(username):
    return get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def get_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def list_users():
    return _q("SELECT user_id, username, role FROM users ORDER BY username")


def set_role(user_id, role):
    _exec("UPDATE users SET role=? WHERE user_id=?", (role, user_id))


def count_admins():
    return get_db().execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]


# ---------- patients ----------
def list_patients(search=None):
    if search:
        like = f"%{search}%"
        return _q("""SELECT p.*, (SELECT COUNT(*) FROM admissions a WHERE a.patient_id=p.patient_id) AS n_adm
                     FROM patients p WHERE p.name LIKE ? OR p.phone LIKE ? OR CAST(p.patient_id AS TEXT)=?
                     ORDER BY p.name LIMIT 200""", (like, like, search.strip()))
    return _q("""SELECT p.*, (SELECT COUNT(*) FROM admissions a WHERE a.patient_id=p.patient_id) AS n_adm
                 FROM patients p ORDER BY p.patient_id DESC LIMIT 200""")


def count_patients():
    return get_db().execute("SELECT COUNT(*) FROM patients").fetchone()[0]


def get_patient(pid):
    return get_db().execute("SELECT * FROM patients WHERE patient_id=?", (pid,)).fetchone()


def create_patient(d):
    return _exec("INSERT INTO patients (name,age,gender,phone,blood_group) VALUES (?,?,?,?,?)",
                 (d["name"], d["age"], d["gender"], d["phone"], d["blood_group"]))


def update_patient(pid, d):
    _exec("UPDATE patients SET name=?, age=?, gender=?, phone=?, blood_group=? WHERE patient_id=?",
          (d["name"], d["age"], d["gender"], d["phone"], d["blood_group"], pid))


def delete_patient(pid):
    _exec("DELETE FROM patients WHERE patient_id=?", (pid,))


def patient_ids():
    return {r[0] for r in get_db().execute("SELECT patient_id FROM patients")}


def insert_patients(rows):
    db = get_db()
    db.executemany("INSERT INTO patients (name,age,gender,phone,blood_group) VALUES (:name,:age,:gender,:phone,:blood_group)", rows)
    db.commit()


# ---------- admissions ----------
def admissions_df():
    df = pd.read_sql_query("""SELECT a.admission_id, a.patient_id, p.name, p.age, p.gender,
                                     a.admission_date, a.discharge_date, a.diagnosis, a.department
                              FROM admissions a JOIN patients p ON p.patient_id=a.patient_id
                              ORDER BY a.admission_date""", get_db())
    df["admission_date"] = pd.to_datetime(df["admission_date"])
    df["discharge_date"] = pd.to_datetime(df["discharge_date"])
    return df


def list_admissions(pid):
    return _q("SELECT * FROM admissions WHERE patient_id=? ORDER BY admission_date DESC", (pid,))


def get_admission(aid):
    return get_db().execute("SELECT * FROM admissions WHERE admission_id=?", (aid,)).fetchone()


def create_admission(pid, d):
    return _exec("""INSERT INTO admissions (patient_id,admission_date,discharge_date,diagnosis,department)
                    VALUES (?,?,?,?,?)""", (pid, d["admission_date"], d["discharge_date"], d["diagnosis"], d["department"]))


def discharge_admission(aid, date):
    _exec("UPDATE admissions SET discharge_date=? WHERE admission_id=? AND discharge_date IS NULL AND ? >= admission_date",
          (date, aid, date))


def insert_admissions(rows):
    db = get_db()
    db.executemany("""INSERT INTO admissions (patient_id,admission_date,discharge_date,diagnosis,department)
                      VALUES (:patient_id,:admission_date,:discharge_date,:diagnosis,:department)""", rows)
    db.commit()


def distinct_values(col):
    assert col in ("department", "diagnosis")
    return [r[0] for r in get_db().execute(f"SELECT DISTINCT {col} FROM admissions ORDER BY {col}")]


# ---------- vitals ----------
def vitals_df():
    df = pd.read_sql_query("SELECT patient_id, temperature, bp, pulse, sugar, recorded_at FROM vitals ORDER BY recorded_at", get_db())
    df["recorded_at"] = pd.to_datetime(df["recorded_at"])
    return df


def list_vitals(pid, limit=50):
    return _q("SELECT * FROM vitals WHERE patient_id=? ORDER BY recorded_at DESC LIMIT ?", (pid, limit))


def add_vital(pid, d):
    return _exec("INSERT INTO vitals (patient_id,temperature,bp,pulse,sugar,recorded_at) VALUES (?,?,?,?,?,?)",
                 (pid, d["temperature"], d["bp"], d["pulse"], d["sugar"], d["recorded_at"]))


def insert_vitals(rows):
    db = get_db()
    db.executemany("""INSERT INTO vitals (patient_id,temperature,bp,pulse,sugar,recorded_at)
                      VALUES (:patient_id,:temperature,:bp,:pulse,:sugar,:recorded_at)""", rows)
    db.commit()


# ---------- predictions ----------
def save_predictions(rows):
    db = get_db()
    db.executemany("""INSERT INTO predictions (patient_id,admission_id,risk_score,risk_level,run_id,model_name,run_type,created_by)
                      VALUES (:patient_id,:admission_id,:risk_score,:risk_level,:run_id,:model_name,:run_type,:created_by)""", rows)
    db.commit()


def latest_run_id():
    """Latest batch scoring run (single-patient look-ups do not replace the hospital-wide risk list)."""
    r = get_db().execute("SELECT run_id FROM predictions WHERE run_type='batch' ORDER BY predicted_at DESC, prediction_id DESC LIMIT 1").fetchone()
    return r[0] if r else None


def get_run(run_id):
    return _q("""SELECT pr.*, p.name, p.age, p.gender, a.department, a.diagnosis, a.admission_date, a.discharge_date
                 FROM predictions pr JOIN patients p ON p.patient_id=pr.patient_id
                 JOIN admissions a ON a.admission_id=pr.admission_id
                 WHERE pr.run_id=? ORDER BY pr.risk_score DESC""", (run_id,))


def list_runs(limit=100):
    return _q("""SELECT pr.run_id, pr.model_name, pr.run_type, MAX(pr.predicted_at) AS predicted_at, COUNT(*) AS n,
                        SUM(pr.risk_level='High') AS n_high, SUM(pr.risk_level='Medium') AS n_med,
                        ROUND(AVG(pr.risk_score),3) AS avg_score, u.username
                 FROM predictions pr LEFT JOIN users u ON u.user_id=pr.created_by
                 GROUP BY pr.run_id ORDER BY predicted_at DESC LIMIT ?""", (limit,))


def patient_predictions(pid):
    return _q("""SELECT pr.*, a.diagnosis FROM predictions pr JOIN admissions a ON a.admission_id=pr.admission_id
                 WHERE pr.patient_id=? ORDER BY pr.predicted_at DESC""", (pid,))
