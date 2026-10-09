"""
Fetches ALL party agencies from Master.xml and updates DB.
Uses exact LEDGER NAME match only - no partial matching.
Run: venv\Scripts\python.exe fetch_all_agencies.py
"""
import re, html, psycopg2

print("Reading Master.xml...")
with open("Master.xml","rb") as f:
    raw = f.read()
try: text = raw.decode("utf-16-le", errors="ignore")
except: text = raw.decode("utf-8", errors="ignore")
print(f"Size: {len(text):,} chars")

DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Get all party names from tickets
cur.execute("SELECT DISTINCT party_name FROM tickets")
ticket_parties = {r[0].upper(): r[0] for r in cur.fetchall()}

updated = skipped = no_agency = 0

for m in re.finditer(r'<LEDGER\s+NAME="([^"]+)"[^>]*>(.*?)</LEDGER>', text, re.DOTALL):
    name  = html.unescape(m.group(1).strip())
    block = m.group(2)

    # Only process if party exists in tickets (exact match)
    if name.upper() not in ticket_parties:
        skipped += 1
        continue

    ticket_name = ticket_parties[name.upper()]

    # Get agency UDF - case insensitive
    agency = re.search(r'(?i)BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)<', block)
    ag = html.unescape(agency.group(1).strip()) if agency else ''

    if not ag:
        no_agency += 1
        continue

    # Update tickets and tally_party_master
    cur.execute("UPDATE tickets SET agency_name=%s WHERE party_name=%s", (ag, ticket_name))
    cur.execute("UPDATE tally_party_master SET agency_name=%s WHERE party_name=%s", (ag, ticket_name))
    cur.execute("""INSERT INTO manual_agency_override(party_name,agency_name)
                   VALUES(%s,%s) ON CONFLICT(party_name)
                   DO UPDATE SET agency_name=EXCLUDED.agency_name""", (ticket_name, ag))
    updated += 1

conn.commit()
print(f"Updated: {updated} | No agency: {no_agency} | Not in tickets: {skipped}")

# Show sample
cur.execute("SELECT party_name, agency_name FROM tickets WHERE agency_name IS NOT NULL ORDER BY party_name LIMIT 10")
print("\nSample agency assignments:")
for r in cur.fetchall():
    print(f"  {r[0][:40]:<40} → {r[1]}")

cur.close()
conn.close()
print("\nDone - all agencies synced from Master.xml")
