"""
Syncs ALL party data from Master.xml:
1. Party mobile (LEDGERMOBILE)
2. Agency name (UDF:BMstLedAgencyNameUdf) 
3. Agency mobile (UDF:BGrpBrokerGroupMoUdf)
4. Credit period (BILLCREDITPERIOD)
Run: venv\Scripts\python.exe sync_from_master.py
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

# Get all parties from tickets
cur.execute("SELECT DISTINCT party_name FROM tickets")
ticket_parties = {r[0].upper(): r[0] for r in cur.fetchall()}

updated = 0
for m in re.finditer(r'<LEDGER\s+NAME="([^"]+)"[^>]*>(.*?)</LEDGER>', text, re.DOTALL):
    name  = html.unescape(m.group(1).strip())
    block = m.group(2)

    if name.upper() not in ticket_parties:
        continue

    ticket_name = ticket_parties[name.upper()]

    # Extract fields
    def get(tag):
        r = re.search(r'(?i)<' + tag + r'[^>]*>(.*?)</', block)
        return html.unescape(r.group(1).strip()) if r else ''

    mobile   = get('LEDGERMOBILE') or get('PHONENUMBER')
    agency   = re.search(r'(?i)BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)<', block)
    ag       = html.unescape(agency.group(1).strip()) if agency else ''
    ag_mob   = re.search(r'(?i)BGRPBROKERGROUPMOUDF[^>]*>(.*?)<', block)
    ag_m     = html.unescape(ag_mob.group(1).strip()) if ag_mob else ''
    credit   = get('BILLCREDITPERIOD')
    credit_days = ''
    if credit:
        cm = re.search(r'(\d+)', credit)
        if cm: credit_days = cm.group(1)

    # Update tickets
    updates = []
    vals = []
    if mobile:
        updates.append("party_mobile=%s"); vals.append(mobile)
    if ag:
        updates.append("agency_name=%s"); vals.append(ag)
    if credit_days:
        updates.append("credit_days=%s"); vals.append(credit_days)

    if updates:
        vals.append(ticket_name)
        cur.execute(f"UPDATE tickets SET {','.join(updates)} WHERE party_name=%s", vals)

    # Update tally_agency_master mobile if agency mobile exists
    if ag and ag_m:
        cur.execute("""INSERT INTO tally_agency_master(agency_name, mobile)
                       VALUES(%s,%s)
                       ON CONFLICT(agency_name) DO UPDATE SET mobile=EXCLUDED.mobile
                       WHERE tally_agency_master.mobile IS NULL OR tally_agency_master.mobile=''""",
                    (ag, ag_m))

    # Update tally_party_master
    if ag:
        cur.execute("UPDATE tally_party_master SET agency_name=%s WHERE party_name=%s", (ag, ticket_name))

    # Manual override
    if ag:
        cur.execute("""INSERT INTO manual_agency_override(party_name,agency_name)
                       VALUES(%s,%s) ON CONFLICT(party_name)
                       DO UPDATE SET agency_name=EXCLUDED.agency_name""", (ticket_name, ag))

    updated += 1

conn.commit()
print(f"Updated {updated} parties from Master.xml")

# Check problem parties
for p in ['M S RAMAYYA SHOPPING MALL','VARDHAMAN AGENCY','MUKESH TEXTILE AGENCY',
          'R B TEXTILE AGENCY','MAHARAJA AGENCY','MEM SAAB']:
    cur.execute("SELECT party_name, agency_name, party_mobile FROM tickets WHERE party_name ILIKE %s LIMIT 1", (f"%{p}%",))
    r = cur.fetchone()
    if r: print(f"  {r[0][:40]} | agency={r[1]} | mobile={r[2]}")

cur.close()
conn.close()
print("Done")
