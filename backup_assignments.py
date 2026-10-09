import subprocess, sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "--quiet"])

import psycopg2, csv, os, glob
from datetime import datetime, timedelta

DB = dict(host="localhost", port=5432, dbname="tally_erp", user="postgres", password="7sW9U0JRHzvxrYkLe9kr")

BACKUP_DIR = os.path.join("C:\\", "Users", "user5", "Downloads", "RecoveryOS_Backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
fname = os.path.join(BACKUP_DIR, f"assignments_{ts}.csv")

conn = psycopg2.connect(**DB)
cur  = conn.cursor()

cur.execute("""
    SELECT party_name, ticket_number, assigned_to, net_due, pending_amount,
           party_mobile, agency_name, party_state, status, synced_at
    FROM tickets
    WHERE assigned_to IS NOT NULL AND assigned_to != ''
    ORDER BY assigned_to, party_name
""")
rows = cur.fetchall()
cols = ["party_name","ticket_number","assigned_to","net_due","pending_amount",
        "party_mobile","agency_name","party_state","status","synced_at"]

with open(fname, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(cols)
    w.writerows(rows)

print(f"Backed up {len(rows)} assignments to:")
print(f"  {fname}")

cur.close()
conn.close()

cutoff   = datetime.now() - timedelta(days=7)
all_files = sorted(glob.glob(os.path.join(BACKUP_DIR, "assignments_*.csv")))
deleted = 0
for f in all_files:
    if datetime.fromtimestamp(os.path.getmtime(f)) < cutoff:
        os.remove(f); deleted += 1

all_files = sorted(glob.glob(os.path.join(BACKUP_DIR, "assignments_*.csv")))
if len(all_files) > 7:
    for f in all_files[:-7]:
        os.remove(f); deleted += 1

print(f"Deleted {deleted} old backup(s)")
remaining = sorted(glob.glob(os.path.join(BACKUP_DIR, "assignments_*.csv")))
print(f"Backups retained: {len(remaining)}")
for f in remaining:
    print(f"  {os.path.basename(f)}")
