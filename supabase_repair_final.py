"""
supabase_repair_final.py — Fix semester mis-assignment directly in Supabase
"""
import os, json
from urllib.parse import unquote

with open(".env") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

raw_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "")
at_split = raw_url.rsplit("@", 1)
user_pass = at_split[0]
host_db   = at_split[1]
colon_idx = user_pass.index(":")
db_user = user_pass[:colon_idx]
db_pass = unquote(user_pass[colon_idx+1:])
host_port, dbname = host_db.split("/", 1)
db_host, db_port = host_port.rsplit(":", 1) if ":" in host_port else (host_port, "5432")

import psycopg2
conn = psycopg2.connect(host=db_host, port=int(db_port), user=db_user,
                        password=db_pass, dbname=dbname, sslmode="require",
                        connect_timeout=15, options="-csearch_path=public")
cur = conn.cursor()
print("Connected to Supabase (public schema)")

# ── Step 1: Show all semesters ─────────────────────────────────────────────
cur.execute("SELECT id, semester_number FROM public.semesters ORDER BY semester_number")
rows = cur.fetchall()
print(f"\nSemesters ({len(rows)}):")
sems = {}
for r in rows:
    sems[r[1]] = r[0]
    print(f"  Semester {r[1]}  id={r[0][:8]}")

# ── Step 2: Show all subjects with semester ────────────────────────────────
cur.execute("""
    SELECT sub.id, sub.name, sub.code, sem.semester_number
    FROM public.subjects sub
    LEFT JOIN public.semesters sem ON sub.semester_id = sem.id
    ORDER BY sem.semester_number, sub.name
""")
all_subjects = cur.fetchall()
print(f"\nAll subjects ({len(all_subjects)}):")
for r in all_subjects:
    print(f"  Sem{r[3] or '?'} | [{r[2] or 'NO-CODE'}] {r[1][:55]}")

# ── Step 3: Find subjects wrongly in Semester 3 ────────────────────────────
# These codes are elective slots (K3=3rd elective, not Semester 3)
# Based on the uploaded Semester 5 PDF, these should be Semester 5
ELECTIVE_CODES_IN_WRONG_SEM = ['ITUETK3', 'ITUETK4', 'ITUETK5', 'ITUETK6', 'ITUELT1']

to_fix = [(r[0], r[1], r[2], r[3]) for r in all_subjects
          if r[2] in ELECTIVE_CODES_IN_WRONG_SEM and r[3] == 3]

if not to_fix:
    print("\nNo subjects found with those codes in Semester 3.")
    # Check if they exist elsewhere
    found_elsewhere = [(r[0], r[1], r[2], r[3]) for r in all_subjects
                       if r[2] in ELECTIVE_CODES_IN_WRONG_SEM]
    if found_elsewhere:
        print("These codes exist in:")
        for r in found_elsewhere:
            print(f"  Sem{r[3]} | [{r[2]}] {r[1]}")
    conn.close()
    exit(0)

print(f"\n{'='*55}")
print(f"SUBJECTS TO MOVE: Semester 3 -> Semester 5")
print(f"{'='*55}")
for r in to_fix:
    print(f"  [{r[2]}] {r[1]}")

sem5_id = sems.get(5)
if not sem5_id:
    print("\nERROR: Semester 5 not in DB. Cannot proceed.")
    conn.close()
    exit(1)

print(f"\nTarget: Semester 5  id={sem5_id[:8]}")
print()
confirm = input("Apply repair? (yes/no): ").strip().lower()
if confirm != "yes":
    print("Cancelled.")
    conn.close()
    exit(0)

# ── Step 4: Apply repair ───────────────────────────────────────────────────
fixed_subjects = 0
fixed_docs = 0

for sub_id, sub_name, sub_code, old_sem in to_fix:
    # Move subject to Semester 5
    cur.execute(
        "UPDATE public.subjects SET semester_id = %s WHERE id = %s",
        (sem5_id, sub_id)
    )
    fixed_subjects += 1

    # Get all docs for this subject
    cur.execute(
        "SELECT id, structured_json FROM public.documents WHERE subject_id = %s",
        (sub_id,)
    )
    docs = cur.fetchall()

    for doc_id, sj in docs:
        if sj:
            if isinstance(sj, str):
                sj = json.loads(sj)
            elif not isinstance(sj, dict):
                sj = {}
            sj["Semester"] = "5"
            cur.execute(
                "UPDATE public.documents SET semester_id = %s, structured_json = %s WHERE id = %s",
                (sem5_id, json.dumps(sj), doc_id)
            )
        else:
            cur.execute(
                "UPDATE public.documents SET semester_id = %s WHERE id = %s",
                (sem5_id, doc_id)
            )
        fixed_docs += 1

    print(f"  OK: [{sub_code}] '{sub_name}' + {len(docs)} doc(s) -> Semester 5")

conn.commit()
print(f"\n[SUCCESS] Committed: {fixed_subjects} subjects, {fixed_docs} documents moved to Semester 5")

# ── Step 5: Final verification ─────────────────────────────────────────────
print("\n=== FINAL STATE ===")
cur.execute("""
    SELECT sub.name, sub.code, sem.semester_number
    FROM public.subjects sub
    JOIN public.semesters sem ON sub.semester_id = sem.id
    ORDER BY sem.semester_number, sub.name
""")
for r in cur.fetchall():
    print(f"  Sem{r[2]} | [{r[1] or 'NO-CODE'}] {r[0][:55]}")

conn.close()
print("\nRepair complete. Open the app and verify subjects appear in the correct semester.")
