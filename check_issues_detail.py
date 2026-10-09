import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# 1. RADHE RADHE (NASIK) duplicate - check tickets JOIN
print("=== RADHE RADHE (NASIK) in tickets ===")
cur.execute("SELECT party_name, party_mobile, agency_name, net_due FROM tickets WHERE party_name='RADHE RADHE (NASIK)'")
for r in cur.fetchall():
    print(f"  mobile={r[1]} agency={r[2]} net={float(r[3] or 0):,.0f}")

# Check tally_agency_master for its agency
cur.execute("SELECT agency_name FROM tickets WHERE party_name='RADHE RADHE (NASIK)'")
ag = cur.fetchone()
if ag and ag[0]:
    cur.execute("SELECT agency_name, mobile FROM tally_agency_master WHERE agency_name=%s", (ag[0],))
    for r in cur.fetchall():
        print(f"  tam: {r[0]} mobile={r[1]}")

# 2. R P PATEL - search in tally_party_master
print("\n=== R P PATEL in tally_party_master ===")
cur.execute("SELECT party_name, mobile FROM tally_party_master WHERE party_name ILIKE '%R%P%PATEL%' OR party_name ILIKE '%RP%PATEL%'")
for r in cur.fetchall():
    print(f"  {r[0]} | mobile={r[1]}")

# 3. MEM SAAB - check manual_agency_override
print("\n=== MEM SAAB in manual_agency_override ===")
cur.execute("SELECT party_name, agency_name FROM manual_agency_override WHERE party_name ILIKE '%MEM SAAB%'")
for r in cur.fetchall():
    print(f"  {r[0]} | agency={r[1]}")

cur.close()
conn.close()
