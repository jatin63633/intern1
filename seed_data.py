"""Creates SYNTHETIC demo data (no real patients): users, ~1,500 patients, ~2 years of admissions and vitals.
Run:  python seed_data.py"""
from datetime import date, timedelta
import numpy as np
from werkzeug.security import generate_password_hash
from app import create_app
import repo

FIRST = ["Aarav","Vihaan","Aditya","Arjun","Rohan","Karthik","Suresh","Ramesh","Anil","Mohan","Priya","Ananya","Diya","Kavya","Meera","Lakshmi","Sunita","Anjali","Divya","Rekha","Farah","Imran","John","Mary","Asha"]
LAST = ["Sharma","Iyer","Reddy","Nair","Gupta","Rao","Patel","Kumar","Singh","Menon","Das","Joshi","Shetty","Hegde","Khan","Fernandes","Pillai","Naidu","Gowda","Bhat"]
# diagnosis: (department, mean LOS, base readmission logit, typical age)
DX = {
    "Heart Failure": ("Cardiology", 6, -1.1, 68), "Myocardial Infarction": ("Cardiology", 5, -1.7, 60),
    "Hypertensive Crisis": ("Cardiology", 2, -2.1, 55), "COPD Exacerbation": ("Pulmonology", 5, -1.2, 66),
    "Pneumonia": ("Pulmonology", 4, -1.9, 55), "Diabetic Ketoacidosis": ("Endocrinology", 4, -1.4, 40),
    "Hip Fracture": ("Orthopedics", 7, -2.3, 74), "Knee Replacement": ("Orthopedics", 3, -2.9, 64),
    "Stroke": ("Neurology", 8, -1.8, 66), "Chronic Kidney Disease": ("Nephrology", 5, -1.2, 62),
    "Gastroenteritis": ("General Medicine", 2, -2.8, 35), "Urinary Tract Infection": ("General Medicine", 3, -2.4, 52),
}
CHRONIC = {"Heart Failure", "COPD Exacerbation", "Chronic Kidney Disease", "Diabetic Ketoacidosis"}


def vitals(rng, dx, diabetic, when):
    fever = dx in ("Pneumonia", "Urinary Tract Infection") and rng.random() < .5
    return {"temperature": round(float(rng.normal(37.0, .35) + (1.1 if fever else 0)), 1),
            "bp": f"{int(rng.normal(128 + (12 if 'Hyper' in dx else 0), 14))}/{int(rng.normal(80, 8))}",
            "pulse": int(rng.normal(80 + (8 if dx == 'Heart Failure' else 0), 10)),
            "sugar": round(float(rng.normal(108, 18) + (65 if diabetic else 0) + (90 if 'Ketoacidosis' in dx else 0)), 0),
            "recorded_at": when.strftime("%Y-%m-%d 08:00:00")}


def main(n_patients=1500, seed=11):
    app, rng, today = create_app(), np.random.default_rng(seed), date.today()
    start = today - timedelta(days=730)
    with app.app_context():
        for u, pw, role in [("admin", "admin12345", "admin"), ("doctor1", "doctor12345", "doctor"), ("staff1", "staff12345", "staff")]:
            if not repo.get_user_by_name(u):
                repo.create_user(u, generate_password_hash(pw), role)
        if repo.count_patients():
            print("Patients already exist - skipping data generation."); return
        dx_names = list(DX)
        n_adm = n_cur = 0
        for _ in range(n_patients):
            diabetic = rng.random() < .28
            fav = dx_names[rng.integers(len(dx_names))]
            age = int(np.clip(rng.normal(DX[fav][3], 13), 1, 98))
            pid = repo.create_patient({"name": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "age": age,
                                       "gender": str(rng.choice(["Male", "Female", "Other"], p=[.5, .48, .02])),
                                       "phone": "9" + "".join(str(d) for d in rng.integers(0, 10, 9)),
                                       "blood_group": str(rng.choice(["A+", "B+", "O+", "AB+", "A-", "B-", "O-", "AB-"], p=[.22, .3, .3, .07, .03, .04, .03, .01]))})
            t = today - timedelta(days=int(rng.integers(1, 9))) if rng.random() < .03 else start + timedelta(days=int(rng.integers(0, 720)))
            prior, prev_dis = 0, None
            vit_rows, adm_rows = [], []
            while t < today - timedelta(days=1):
                dx = fav if (fav in CHRONIC and rng.random() < .7) or rng.random() < .55 else dx_names[rng.integers(len(dx_names))]
                dept, mlos, base, _ = DX[dx]
                los = int(max(1, round(rng.normal(mlos, 1.8))))
                dis = t + timedelta(days=los)
                ongoing = dis > today
                v_dis = vitals(rng, dx, diabetic, min(dis, today))
                vit_rows += [vitals(rng, dx, diabetic, t), v_dis] + ([vitals(rng, dx, diabetic, t + timedelta(days=los // 2))] if los > 3 else [])
                adm_rows.append({"patient_id": pid, "admission_date": t.isoformat(), "discharge_date": None if ongoing else dis.isoformat(),
                                 "diagnosis": dx, "department": dept})
                if ongoing:
                    n_cur += 1; break
                sugar = v_dis["sugar"]
                logit = (base - .8 + .03 * (age - 60) + .55 * min(prior, 4) + .012 * (sugar - 120) * (sugar > 160)
                         + .1 * (los - mlos) + (.5 if los <= 1 else 0) + rng.normal(0, .35))
                p = 1 / (1 + np.exp(-logit))
                prior += 1
                if rng.random() < p:
                    t = dis + timedelta(days=int(rng.integers(3, 31)))
                elif rng.random() < .22:
                    t = dis + timedelta(days=int(rng.integers(40, 320)))
                else:
                    break
            repo.insert_admissions(adm_rows); repo.insert_vitals([{**v, "patient_id": pid} for v in vit_rows]); n_adm += len(adm_rows)
        import csv
        with open("sample_patients.csv", "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["name", "age", "gender", "phone", "blood_group"])
            w.writerows([["Test Patient One", 54, "Male", "9876543210", "O+"], ["Test Patient Two", 31, "Female", "9123456780", "A-"], ["Bad Row", 400, "X", "1", "Z9"]])
        print(f"Seeded {n_patients} synthetic patients, {n_adm} admissions ({n_cur} current inpatients).")
        print("Logins: admin/admin12345, doctor1/doctor12345, staff1/staff12345")


if __name__ == "__main__":
    main()
