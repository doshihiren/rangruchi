import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

cur.execute("SELECT agency_name FROM tickets WHERE party_name='M S RAMAYYA SHOPPING MALL'")
ag = cur.fetchone()[0]
print(f"Current agency: {ag!r} len={len(ag)} last={ord(ag[-1])}")

cur.execute("SELECT agency_name, mobile FROM tally_agency_master WHERE agency_name ILIKE '%VARDHAMAN%'")
for r in cur.fetchall():
    print(f"tam: {r[0]!r} len={len(r[0])} mobile={r[1]}")

cur.close()
conn.close()
