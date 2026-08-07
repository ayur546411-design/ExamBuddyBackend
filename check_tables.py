"""check_tables.py — See what tables exist and what data is in semesters/subjects"""
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
                        password=db_pass, dbname=dbname, sslmode="require", connect_timeout=15)
cur = conn.cursor()
print("Connected!")

# Check search_path
cur.execute("SHOW search_path")
print(f"search_path: {cur.fetchone()}")

# List all tables in all schemas
cur.execute("""
    SELECT schemaname, tablename 
    FROM pg_tables 
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY schemaname, tablename
""")
tables = cur.fetchall()
print(f"\nAll user tables ({len(tables)}):")
for t in tables:
    print(f"  {t[0]}.{t[1]}")

# Try each schema to find semesters
for schema, tbl in tables:
    if tbl == 'semesters':
        cur.execute(f"SELECT COUNT(*) FROM {schema}.semesters")
        cnt = cur.fetchone()[0]
        cur.execute(f"SELECT id[:8], semester_number FROM {schema}.semesters LIMIT 5")
        rows = cur.fetchall()
        print(f"\n{schema}.semesters has {cnt} rows:")
        for r in rows:
            print(f"  id={r[0]} sem_num={r[1]}")

conn.close()
