import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Check exact agency name in tickets vs tam
cur.execute("SELECT agency_name FROM tickets WHERE party_name='M S RAMAYYA SHOPPING MALL'")
ag = cur.fetchone()[0]
print(f"tickets agency: {ag!r}")
print(f"length: {len(ag)}")
print(f"last char: {ag[-1]!r} (ord={ord(ag[-1])})")

# Check tam
cur.execute("SELECT agency_name, mobile FROM tally_agency_master WHERE agency_name LIKE %s", (ag + '%',))
for r in cur.fetchall():
    print(f"tam LIKE match: {r[0]!r} mobile={r[1]}")

cur.execute("SELECT agency_name FROM tally_agency_master WHERE agency_name LIKE 'VARDHAMAN AGENCY%'")
for r in cur.fetchall():
    print(f"tam VARDHAMAN: {r[0]!r}")

cur.close()
conn.close()
