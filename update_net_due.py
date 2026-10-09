"""
update_net_due.py
Net due = overdue bills - PDC - on_account
(original working formula - Rs 4.1Cr total)
Run: venv\\Scripts\\python.exe update_net_due.py
"""
import psycopg2

DB = dict(host="localhost", port=5432, dbname="tally_erp",
          user="postgres", password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

cur.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS net_due NUMERIC DEFAULT 0")
conn.commit()
print("net_due column ready")

cur.execute("""
    UPDATE tickets t SET credit_days = sm.credit_period_days
    FROM salesperson_mapping sm
    WHERE regexp_replace(upper(sm.party_name),'\\s+',' ','g')
        = regexp_replace(upper(t.party_name),'\\s+',' ','g')
    AND sm.credit_period_days IS NOT NULL AND sm.credit_period_days > 0
    AND t.credit_days IS DISTINCT FROM sm.credit_period_days::text
""")
conn.commit()
print(f"Synced credit_days for {cur.rowcount} parties")

cur.execute("""
    UPDATE tickets t SET net_due = GREATEST(0,
        COALESCE((
            SELECT SUM(b.pending_amount)
            FROM billwise b
            WHERE regexp_replace(upper(b.party_name),'\\s+',' ','g')
                = regexp_replace(upper(t.party_name),'\\s+',' ','g')
            AND b.pending_amount > 0
            AND b.invoice_no NOT ILIKE '%%on account%%'
            AND b.invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
            AND TO_DATE(b.invoice_date,'DD-Mon-YY')
                + (COALESCE(NULLIF(t.credit_days,'')::int, 30) || ' days')::interval < CURRENT_DATE
        ), 0)
        - COALESCE((
            SELECT SUM(p.amount) FROM pdc_entries p
            WHERE regexp_replace(upper(p.party_name),'\\s+',' ','g')
                = regexp_replace(upper(t.party_name),'\\s+',' ','g')
        ), 0)
        - COALESCE((
            SELECT SUM(b.pending_amount) FROM billwise b
            WHERE regexp_replace(upper(b.party_name),'\\s+',' ','g')
                = regexp_replace(upper(t.party_name),'\\s+',' ','g')
            AND b.pending_amount > 0 AND b.invoice_no ILIKE '%%on account%%'
        ), 0)
    )
""")
conn.commit()
print(f"Updated net_due for {cur.rowcount} parties")

cur.execute("ALTER TABLE followups ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE")
cur.execute("""
    UPDATE followups f SET archived=TRUE FROM tickets t
    WHERE f.party_name=t.party_name AND COALESCE(t.net_due,0)=0
    AND (f.archived IS NULL OR f.archived=FALSE)
""")
conn.commit()
print(f"Auto-archived {cur.rowcount} followups for cleared parties")

cur.execute("""
    UPDATE followups f SET archived=FALSE FROM tickets t
    WHERE f.party_name=t.party_name AND COALESCE(t.net_due,0)>0 AND f.archived=TRUE
""")
conn.commit()

cur.execute("SELECT COUNT(*), SUM(net_due) FROM tickets WHERE net_due>0")
r = cur.fetchone()
print(f"\nParties with net_due > 0: {r[0]} | Total: Rs {float(r[1] or 0):,.0f}")
cur.execute("SELECT COUNT(*) FROM tickets WHERE net_due=0 AND pending_amount>0")
print(f"Parties with pending but net_due=0 (hidden): {cur.fetchone()[0]}")

for label, pattern in [
    ("L N Textile", "%L%N%TEXT%"),
    ("Shree Radhey Krishna", "%RADHEY KRISHNA%"),
    ("Mahadev", "%MAHADEV%"),
]:
    cur.execute("""
        SELECT t.party_name, t.credit_days, t.net_due, t.pending_amount,
               COALESCE((SELECT SUM(p.amount) FROM pdc_entries p WHERE p.party_name=t.party_name),0) pdc
        FROM tickets t WHERE t.party_name ILIKE %s LIMIT 5
    """, (pattern,))
    print(f"\n=== {label} ===")
    for row in cur.fetchall():
        print(f"  {row[0]} | credit={row[1]} | pending={float(row[3] or 0):,.0f} | pdc={float(row[4] or 0):,.0f} | net={float(row[2] or 0):,.0f}")

cur.close()
conn.close()
print("\nDone!")
