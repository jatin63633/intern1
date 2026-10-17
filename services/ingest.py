"""CSV upload: safe storage + row-by-row validation (reuses validation.py)."""
import csv
import os
import uuid
from werkzeug.utils import secure_filename
from services import validation as v

KINDS = {
    "patients": ({"name", "age", "gender"}, "name, age, gender [, phone, blood_group]"),
    "admissions": ({"patient_id", "admission_date", "diagnosis", "department"}, "patient_id, admission_date, diagnosis, department [, discharge_date]"),
    "vitals": ({"patient_id", "recorded_at"}, "patient_id, recorded_at [, temperature, bp, pulse, sugar]"),
}


def allowed(filename, exts):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in exts


def save_upload(fs, folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{uuid.uuid4().hex[:10]}_{secure_filename(fs.filename) or 'upload.csv'}")
    fs.save(path)
    return path


def parse(path, kind, known_patient_ids, max_rows):
    """Returns (valid_rows, report). Nothing is written here."""
    required, _ = KINDS[kind]
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        if not rd.fieldnames:
            raise ValueError("The file is empty.")
        rd.fieldnames = [f.strip().lower() for f in rd.fieldnames]
        missing = required - set(rd.fieldnames)
        if missing:
            raise ValueError("Missing required column(s): " + ", ".join(sorted(missing)))
        rows, errors, total = [], [], 0
        for i, raw in enumerate(rd, start=2):
            total += 1
            if total > max_rows:
                raise ValueError(f"File exceeds the {max_rows:,} row limit.")
            raw = {k: (val or "").strip() for k, val in raw.items() if k}
            if kind == "patients":
                clean, err = v.clean_patient(raw)
            else:
                clean, err = (v.clean_admission(raw) if kind == "admissions" else v.clean_vital(raw))
                if not err:
                    try:
                        pid = int(raw.get("patient_id", ""))
                        if pid not in known_patient_ids:
                            err = f"unknown patient_id {pid}"
                        else:
                            clean["patient_id"] = pid
                    except ValueError:
                        err = "patient_id must be a number"
            if err:
                errors.append(f"row {i}: {err}")
            else:
                rows.append(clean)
    return rows, {"total": total, "imported": len(rows), "invalid": len(errors), "errors": errors[:8]}
