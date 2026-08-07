"""
check_connection_mode.py — Try session mode port and direct connection
"""
import os
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

print(f"Original host={db_host} port={db_port}")

import psycopg2

def try_connect(host, port, user, password, dbname, label):
    try:
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password,
            dbname=dbname, sslmode="require", connect_timeout=10
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM public.semesters")
        count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM public.subjects")
        subj_count = cur.fetchone()[0]
        conn.close()
        print(f"  [{label}] port={port}: Connected OK | semesters={count} | subjects={subj_count}")
        return count > 0
    except Exception as e:
        print(f"  [{label}] port={port}: FAILED - {str(e)[:80]}")
        return False

print("\nTrying different connection modes:")
# Supabase pooler transaction mode = 5432
# Supabase pooler session mode = 6543
# Supabase direct = 5432 on a different host (db.xxx.supabase.co)
try_connect(db_host, 5432, db_user, db_pass, dbname, "Pooler port 5432")
try_connect(db_host, 6543, db_user, db_pass, dbname, "Pooler port 6543 (session)")

# Try direct connection host
direct_host = db_host.replace("aws-1-ap-south-1.pooler", "db")
direct_host_alt = db_host.replace("aws-1-ap-south-1.pooler", "db").replace(".pooler", "")
print(f"  Direct host guess: {direct_host}")
try_connect(direct_host, 5432, db_user.replace(".kqnhlyrupbowdnsjclli", ""), db_pass, dbname, "Direct connection")
