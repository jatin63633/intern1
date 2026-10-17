"""Presentation layer: validate input, call services/repo, render templates or JSON."""
import csv
import io
import sqlite3
import uuid
from datetime import date
import numpy as np
import pandas as pd
from flask import (Blueprint, Response, current_app, flash, g, jsonify, redirect,
                   render_template, request, url_for)
import repo
from auth import login_required, role_required
from services import analytics, features, ingest, model, validation

bp = Blueprint("main", __name__)
CLINICAL = ("admin", "doctor")


def _frames():
    adm, vit = repo.admissions_df(), repo.vitals_df()
    return adm, vit, features.build_frame(adm, vit)


def _flt():
    return request.args.get("department", ""), request.args.get("start", ""), request.args.get("end", "")


def _departments():
    return sorted(set(current_app.config["DEPARTMENTS"]) | set(repo.distinct_values("department")))


def _model():
    return model.load(current_app.config["MODEL_FOLDER"])


# ---------------- dashboard ----------------
@bp.route("/")
@bp.route("/dashboard")
@login_required
def dashboard():
    adm, vit, feats = _frames()
    rid = repo.latest_run_id()
    return render_template("dashboard.html", summary=analytics.kpis(adm, feats), dept_stats=analytics.department_stats(adm, feats),
                           top=[r for r in (repo.get_run(rid) if rid else [])][:8], run_id=rid)


# ---------------- patients & medical records ----------------
@bp.route("/patients")
@login_required
def patients():
    q = request.args.get("q", "").strip()
    edit = repo.get_patient(request.args.get("edit", type=int)) if request.args.get("edit") else None
    return render_template("patients.html", patients=repo.list_patients(q or None), q=q, edit=edit,
                           genders=["Male", "Female", "Other"], blood=validation.BLOOD)


@bp.route("/patients/save", methods=["POST"])
@login_required
def patient_save():
    data, err = validation.clean_patient(request.form)
    pid = request.form.get("patient_id", type=int)
    if err:
        flash(f"Patient not saved: {err}.", "danger")
        return redirect(url_for("main.patients", edit=pid) if pid else url_for("main.patients"))
    if pid and repo.get_patient(pid):
        repo.update_patient(pid, data)
        flash("Patient updated.", "success")
    else:
        pid = repo.create_patient(data)
        flash(f"Patient registered (ID {pid}).", "success")
    return redirect(url_for("main.patient_detail", pid=pid))


@bp.route("/patients/<int:pid>")
@login_required
def patient_detail(pid):
    p = repo.get_patient(pid)
    if not p:
        flash("Patient not found.", "danger")
        return redirect(url_for("main.patients"))
    vit = repo.list_vitals(pid)
    chrono = list(reversed(vit))
    chart = {"labels": [v["recorded_at"][:16] for v in chrono], "temperature": [v["temperature"] for v in chrono],
             "pulse": [v["pulse"] for v in chrono], "sugar": [v["sugar"] for v in chrono]}
    return render_template("patient_detail.html", p=p, admissions=repo.list_admissions(pid), vitals=vit, chart=chart,
                           preds=repo.patient_predictions(pid), departments=_departments(),
                           diagnoses=repo.distinct_values("diagnosis"), today=date.today().isoformat())


@bp.route("/patients/<int:pid>/delete", methods=["POST"])
@role_required("admin")
def patient_delete(pid):
    repo.delete_patient(pid)
    flash("Patient and all linked records deleted.", "info")
    return redirect(url_for("main.patients"))


@bp.route("/patients/<int:pid>/admit", methods=["POST"])
@login_required
def admit(pid):
    if not repo.get_patient(pid):
        return redirect(url_for("main.patients"))
    data, err = validation.clean_admission(request.form)
    if err:
        flash(f"Admission not saved: {err}.", "danger")
    else:
        repo.create_admission(pid, data)
        flash("Admission recorded.", "success")
    return redirect(url_for("main.patient_detail", pid=pid))


@bp.route("/admissions/<int:aid>/discharge", methods=["POST"])
@login_required
def discharge(aid):
    a = repo.get_admission(aid)
    if not a:
        return redirect(url_for("main.patients"))
    try:
        d = validation._date(request.form.get("discharge_date"))
        repo.discharge_admission(aid, d)
        flash("Discharge recorded." if d >= a["admission_date"] else "Discharge date cannot precede admission.",
              "success" if d >= a["admission_date"] else "danger")
    except ValueError:
        flash("Enter a valid discharge date.", "danger")
    return redirect(url_for("main.patient_detail", pid=a["patient_id"]))


@bp.route("/patients/<int:pid>/vitals", methods=["POST"])
@login_required
def add_vitals(pid):
    if not repo.get_patient(pid):
        return redirect(url_for("main.patients"))
    data, err = validation.clean_vital(request.form)
    if err:
        flash(f"Vitals not saved: {err}.", "danger")
    else:
        repo.add_vital(pid, data)
        flash("Vitals recorded.", "success")
    return redirect(url_for("main.patient_detail", pid=pid))


# ---------------- upload ----------------
@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    report = None
    if request.method == "POST":
        kind, file = request.form.get("kind"), request.files.get("file")
        if kind not in ingest.KINDS:
            flash("Choose a dataset type.", "danger")
        elif not file or not file.filename:
            flash("Choose a CSV file.", "danger")
        elif not ingest.allowed(file.filename, current_app.config["ALLOWED_EXTENSIONS"]):
            flash("Only .csv files are accepted.", "danger")
        else:
            path = ingest.save_upload(file, current_app.config["UPLOAD_FOLDER"])
            try:
                rows, report = ingest.parse(path, kind, repo.patient_ids(), current_app.config["MAX_UPLOAD_ROWS"])
                {"patients": repo.insert_patients, "admissions": repo.insert_admissions, "vitals": repo.insert_vitals}[kind](rows)
                flash(f"Imported {report['imported']} of {report['total']} {kind} rows.", "success" if rows else "danger")
            except (ValueError, UnicodeDecodeError, csv.Error) as exc:
                flash(f"Upload rejected: {exc}", "danger")
    return render_template("upload.html", kinds=ingest.KINDS, report=report)


# ---------------- analytics ----------------
@bp.route("/analytics")
@login_required
def analytics_page():
    adm, vit, feats = _frames()
    dept, start, end = _flt()
    a = analytics.filter_adm(adm, dept, start, end)
    f = feats[feats["admission_id"].isin(a["admission_id"])] if not feats.empty else feats
    return render_template("analytics.html", departments=_departments(), dept=dept, start=start, end=end,
                           summary=analytics.kpis(a, feats), dept_stats=analytics.department_stats(a, feats),
                           insights=analytics.diagnostic_insights(f) if not f.empty else [])


@bp.route("/api/analytics")
@login_required
def api_analytics():
    adm, vit, feats = _frames()
    a = analytics.filter_adm(adm, *_flt())
    if a.empty:
        return jsonify({"empty": True})
    f = feats[feats["admission_id"].isin(a["admission_id"])]
    return jsonify({"empty": False, "occupancy": analytics.occupancy_monthly(a),
                    "diagnosis": analytics.diagnosis_distribution(a), "los_dept": analytics.los_by_department(f),
                    "los_hist": analytics.los_histogram(f), "trend": analytics.admissions_trend(a),
                    "age": analytics.age_gender(a),
                    "readmit_dept": analytics.readmit_by(f, "department"),
                    "readmit_dx": analytics.readmit_by(f, "diagnosis"),
                    "readmit_age": analytics.readmit_by(f, "age", bins=analytics.AGE_BINS, labels=analytics.AGE_LABELS)})


# ---------------- prediction ----------------
@bp.route("/predict")
@login_required
def predict():
    return render_template("predict.html", bundle=_model(), patients=repo.list_patients(), run_id=repo.latest_run_id(),
                           can_run=g.user["role"] in CLINICAL, cfg=current_app.config)


@bp.route("/predict/train", methods=["POST"])
@role_required(*CLINICAL)
def predict_train():
    _, _, feats = _frames()
    try:
        b = model.train(feats, current_app.config["MODEL_FOLDER"], current_app.config["RISK_HIGH"], current_app.config["RISK_MEDIUM"])
        flash(f"Trained {len(b['comparison'])} models; saved best: {b['name']} (F1 {b['best']['f1']}).", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("main.predict"))


@bp.route("/predict/run", methods=["POST"])
@role_required(*CLINICAL)
def predict_run():
    b = _model()
    if not b:
        flash("Train a model first.", "danger")
        return redirect(url_for("main.predict"))
    window = min(max(request.form.get("window", 30, type=int), 1), 365)
    _, _, feats = _frames()
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=window)
    latest = feats.sort_values(["patient_id", "admission_date"]).groupby("patient_id").tail(1)
    todo = latest[(~latest["discharged"]) | (latest["discharge_date"] >= cutoff)]
    if todo.empty:
        flash("No current inpatients or recent discharges to score in that window.", "info")
        return redirect(url_for("main.predict"))
    scores = model.score(b, todo)
    run_id = uuid.uuid4().hex[:12]
    repo.save_predictions([{"patient_id": int(r.patient_id), "admission_id": int(r.admission_id), "risk_score": round(float(s), 4),
                            "risk_level": model.level(s, b), "run_id": run_id, "model_name": b["name"],
                            "run_type": "batch", "created_by": g.user["user_id"]} for r, s in zip(todo.itertuples(), scores)])
    flash(f"Scored {len(todo)} patients.", "success")
    return redirect(url_for("main.history_run", run_id=run_id))


@bp.route("/predict/patient/<int:pid>", methods=["POST"])
@role_required(*CLINICAL)
def predict_patient(pid):
    b = _model()
    p = repo.get_patient(pid)
    if not b or not p:
        flash("Train a model first and choose a valid patient.", "danger")
        return redirect(url_for("main.predict"))
    _, _, feats = _frames()
    mine = feats[feats["patient_id"] == pid].sort_values("admission_date")
    if mine.empty:
        flash("This patient has no admissions to score.", "danger")
        return redirect(url_for("main.patient_detail", pid=pid))
    row = mine.tail(1)
    s = float(model.score(b, row)[0])
    run_id = uuid.uuid4().hex[:12]
    repo.save_predictions([{"patient_id": pid, "admission_id": int(row.iloc[0]["admission_id"]), "risk_score": round(s, 4),
                            "risk_level": model.level(s, b), "run_id": run_id, "model_name": b["name"], "run_type": "single", "created_by": g.user["user_id"]}])
    return render_template("patient_prediction.html", p=p, row=row.iloc[0].to_dict(), score=s, level=model.level(s, b),
                           drivers=model.explain(b, row), bundle=b, run_id=run_id)


@bp.route("/history")
@login_required
def history():
    return render_template("history.html", runs=repo.list_runs())


@bp.route("/history/<run_id>")
@login_required
def history_run(run_id):
    rows = repo.get_run(run_id)
    if not rows:
        flash("Prediction run not found.", "danger")
        return redirect(url_for("main.history"))
    dept = request.args.get("department", "")
    shown = [r for r in rows if not dept or r["department"] == dept]
    return render_template("prediction_run.html", rows=shown, all_rows=rows, run_id=run_id, dept=dept,
                           departments=sorted({r["department"] for r in rows}))


# ---------------- doctor dashboard ----------------
@bp.route("/doctor")
@role_required(*CLINICAL)
def doctor():
    dept = request.args.get("department", "")
    _, _, feats = _frames()
    rid = repo.latest_run_id()
    run = repo.get_run(rid) if rid else []
    high = [r for r in run if r["risk_level"] == "High" and (not dept or r["department"] == dept)]
    inpatients = analytics.inpatient_status(feats, dept or None) if not feats.empty else []
    return render_template("doctor.html", departments=_departments(), dept=dept, high=high, run_id=rid,
                           run_time=run[0]["predicted_at"] if run else None, inpatients=inpatients,
                           flagged=[i for i in inpatients if i["flags"]])


# ---------------- reports ----------------
def _report_data():
    adm, vit, feats = _frames()
    dept, start, end = _flt()
    a = analytics.filter_adm(adm, dept, start, end)
    return a, feats


@bp.route("/reports")
@login_required
def reports():
    a, feats = _report_data()
    dept, start, end = _flt()
    rid = repo.latest_run_id()
    run = [r for r in (repo.get_run(rid) if rid else []) if r["risk_level"] != "Low" and (not dept or r["department"] == dept)]
    return render_template("reports.html", departments=_departments(), dept=dept, start=start, end=end,
                           summary=analytics.kpis(a, feats), dept_stats=analytics.department_stats(a, feats),
                           dx=analytics.diagnosis_distribution(a, 15) if not a.empty else {"labels": [], "values": []},
                           risk=run, run_id=rid)


@bp.route("/reports/download/<kind>")
@login_required
def reports_download(kind):
    a, feats = _report_data()
    buf, w = io.StringIO(), None
    w = csv.writer(buf)
    if kind == "departments":
        w.writerow(["department", "admissions", "inpatients", "avg_los_days", "avg_daily_census", "readmit_rate_pct"])
        for r in analytics.department_stats(a, feats):
            w.writerow([r["department"], r["admissions"], r["inpatients"], r["avg_los"], r["avg_census"], r["readmit_rate"]])
    elif kind == "diagnoses":
        d = analytics.diagnosis_distribution(a, 50) if not a.empty else {"labels": [], "values": []}
        w.writerow(["diagnosis", "admissions"])
        w.writerows(zip(d["labels"], d["values"]))
    elif kind == "risk":
        rid = repo.latest_run_id()
        w.writerow(["patient_id", "name", "department", "diagnosis", "risk_score", "risk_level", "predicted_at", "model"])
        for r in (repo.get_run(rid) if rid else []):
            w.writerow([r["patient_id"], r["name"], r["department"], r["diagnosis"], r["risk_score"], r["risk_level"], r["predicted_at"], r["model_name"]])
    else:
        return redirect(url_for("main.reports"))
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={kind}_report.csv"})
