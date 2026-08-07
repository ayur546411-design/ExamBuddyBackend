"""
supabase_repair.py — Direct Supabase repair using explicit connection params
"""
import os, json

with open(".env") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

# Parse DATABASE_URL properly
# Format: postgresql+asyncpg://user:password@host:port/database
raw_url = os.environ["DATABASE_URL"]
# Remove scheme
no_scheme = raw_url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")

# Split user:pass@host:port/db  — last @ separates creds from host
at_split = no_scheme.rsplit("@", 1)
user_pass = at_split[0]   # "user:pass" (pass may contain @)
host_db   = at_split[1]   # "host:port/db"

# Split user:pass
colon_idx = user_pass.index(":")
db_user = user_pass[:colon_idx]
db_pass = user_pass[colon_idx+1:]

# URL-decode password
from urllib.parse import unquote
db_pass = unquote(db_pass)

# Split host:port/dbname
host_port, dbname = host_db.split("/", 1)
if ":" in host_port:
    db_host, db_port = host_port.rsplit(":", 1)
else:
    db_host, db_port = host_port, "5432"

print(f"Host: {db_host}")
print(f"Port: {db_port}")
print(f"User: {db_user[:30]}...")
print(f"DB  : {dbname}")

import psycopg2

print("\nConnecting to Supabase...")
conn = psycopg2.connect(
    host=db_host,
    port=int(db_port),
    user=db_user,
    password=db_pass,
    dbname=dbname,
    sslmode="require",
    connect_timeout=15
)
cur = conn.cursor()
print("Connected!")

# ─── Show all semesters ────────────────────────────────────────────────────
cur.execute("SELECT id, semester_number FROM semesters ORDER BY semester_number")
semesters = {row[1]: row[0] for row in cur.fetchall()}
print(f"\nSemesters in DB: {sorted(semesters.keys())}")

if not semesters:
    print("No semesters found!")
    conn.close()
    exit(1)

# ─── Show subjects by semester ─────────────────────────────────────────────
print("\n=== SUBJECTS BY SEMESTER ===")
cur.execute("""
    SELECT sub.id, sub.name, sub.code, sem.semester_number
    FROM subjects sub
    LEFT JOIN semesters sem ON sub.semester_id = sem.id
    ORDER BY sem.semester_number, sub.name
""")
all_subjects = cur.fetchall()
for r in all_subjects:
    print(f"  Sem{r[3] or '?'} | [{r[2] or 'NO-CODE'}] {r[1][:50]}")

# ─── Identify subjects in wrong semester ───────────────────────────────────
# These elective codes appear in Semester 3 but belong in Semester 5
WRONG_IN_SEM3 = ['ITUETK3', 'ITUETK4', 'ITUETK5', 'ITUETK6', 'ITUELT1']

to_move = [r for r in all_subjects if r[2] in WRONG_IN_SEM3 and r[3] == 3]

if not to_move:
    print("\nNo subjects found in Semester 3 with those codes. Nothing to repair.")
    conn.close()
    exit(0)

print(f"\n=== SUBJECTS TO MOVE: Semester 3 -> Semester 5 ===")
for r in to_move:
    print(f"  [{r[2]}] {r[1]}")

sem5_id = semesters.get(5)
if not sem5_id:
    print("ERROR: Semester 5 not found in DB. Cannot repair.")
    conn.close()
    exit(1)

confirm = input("\nMove these subjects to Semester 5? (yes/no): ").strip().lower()
if confirm != "yes":
    print("Cancelled.")
    conn.close()
    exit(0)

# ─── Apply repair ─────────────────────────────────────────────────────────
for r in to_move:
    sub_id = r[0]
    sub_code = r[2]
    sub_name = r[1]

    # Move subject
    cur.execute("UPDATE subjects SET semester_id = %s WHERE id = %s", (sem5_id, sub_id))

    # Get all docs for this subject
    cur.execute("SELECT id, structured_json FROM documents WHERE subject_id = %s", (sub_id,))
    docs = cur.fetchall()

    for doc_id, sj in docs:
        if sj:
            if isinstance(sj, str):
                sj = json.loads(sj)
            sj["Semester"] = "5"
            cur.execute(
                "UPDATE documents SET semester_id = %s, structured_json = %s WHERE id = %s",
                (sem5_id, json.dumps(sj), doc_id)
            )
        else:
            cur.execute("UPDATE documents SET semester_id = %s WHERE id = %s", (sem5_id, doc_id))

    print(f"  Moved [{sub_code}] '{sub_name}' + {len(docs)} doc(s) -> Semester 5")

conn.commit()
print("\n[SUCCESS] Repair committed to Supabase.")

# ─── Verify ────────────────────────────────────────────────────────────────
print("\n=== POST-REPAIR STATE ===")
cur.execute("""
    SELECT sub.name, sub.code, sem.semester_number
    FROM subjects sub
    JOIN semesters sem ON sub.semester_id = sem.id
    ORDER BY sem.semester_number, sub.name
""")
for r in cur.fetchall():
    print(f"  Sem{r[2]} | [{r[1] or 'NO-CODE'}] {r[0][:50]}")

conn.close()
print("\nDone.")
