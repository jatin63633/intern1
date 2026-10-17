"""Input validation shared by web forms and CSV uploads. Returns (clean_dict, error_message|None)."""
import re
from datetime import datetime

GENDERS = {"male": "Male", "female": "Female", "other": "Other"}
BLOOD = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Unknown"]


def _date(v, required=True):
    v = (v or "").strip()
    if not v:
        if required:
            raise ValueError("date required")
        return None
    return datetime.fromisoformat(v.replace("T", " ")).strftime("%Y-%m-%d")


def clean_patient(d):
    try:
        name = re.sub(r"\s+", " ", (d.get("name") or "").strip())
        if not 2 <= len(name) <= 80:
            raise ValueError("name must be 2-80 characters")
        age = int(float(d.get("age")))
        if not 0 <= age <= 120:
            raise ValueError("age must be 0-120")
        gender = GENDERS.get((d.get("gender") or "").strip().lower())
        if not gender:
            raise ValueError("gender must be Male, Female or Other")
        phone = re.sub(r"[^\d+]", "", d.get("phone") or "")
        if phone and not 7 <= len(phone.replace("+", "")) <= 15:
            raise ValueError("phone must have 7-15 digits")
        bg = (d.get("blood_group") or "Unknown").strip().upper().replace("POS", "+").replace("NEG", "-") or "Unknown"
        bg = "Unknown" if bg == "UNKNOWN" else bg
        if bg not in BLOOD:
            raise ValueError("invalid blood group")
        return {"name": name, "age": age, "gender": gender, "phone": phone, "blood_group": bg}, None
    except (ValueError, TypeError) as exc:
        return None, str(exc)


def clean_admission(d):
    try:
        adm, dis = _date(d.get("admission_date")), _date(d.get("discharge_date"), required=False)
        if dis and dis < adm:
            raise ValueError("discharge date is before admission date")
        dx = re.sub(r"\s+", " ", (d.get("diagnosis") or "").strip())
        dept = re.sub(r"\s+", " ", (d.get("department") or "").strip())
        if not 2 <= len(dx) <= 80 or not 2 <= len(dept) <= 60:
            raise ValueError("diagnosis and department are required")
        return {"admission_date": adm, "discharge_date": dis, "diagnosis": dx, "department": dept}, None
    except (ValueError, TypeError) as exc:
        return None, str(exc)


def clean_vital(d):
    def num(key, lo, hi, cast=float):
        raw = (d.get(key) or "").strip() if isinstance(d.get(key), str) else d.get(key)
        if raw in (None, ""):
            return None
        v = cast(float(raw))
        if not lo <= v <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}")
        return v
    try:
        t = num("temperature", 30, 45)
        pulse = num("pulse", 20, 250, int)
        sugar = num("sugar", 20, 800)
        bp = (d.get("bp") or "").strip()
        if bp:
            m = re.fullmatch(r"(\d{2,3})\s*/\s*(\d{2,3})", bp)
            if not m or not (50 <= int(m[1]) <= 260 and 30 <= int(m[2]) <= 160 and int(m[1]) > int(m[2])):
                raise ValueError("bp must look like 120/80 with plausible values")
            bp = f"{int(m[1])}/{int(m[2])}"
        if t is None and not bp and pulse is None and sugar is None:
            raise ValueError("enter at least one vital sign")
        rec = (d.get("recorded_at") or "").strip().replace("T", " ")
        rec = datetime.fromisoformat(rec).strftime("%Y-%m-%d %H:%M:%S") if rec else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {"temperature": t, "bp": bp or None, "pulse": pulse, "sugar": sugar, "recorded_at": rec}, None
    except (ValueError, TypeError) as exc:
        return None, str(exc)
