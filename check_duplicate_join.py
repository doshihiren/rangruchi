import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Check SHREE GANESH TEXTILE in agency master - should be only 1 now
cur.execute("SELECT agency_name, mobile FROM tally_agency_master WHERE agency_name ILIKE '%SHREE GANESH TEXTILE%'")
print("SHREE GANESH TEXTILE in tam:")
for r in cur.fetchall():
    print(f"  {r[0]!r} → {r[1]!r}")

# Check what other agencies might cause duplicates via LIKE join
cur.execute("""
    SELECT t.party_name, COUNT(*) as cnt
    FROM tickets t
    LEFT JOIN tally_agency_master tam
        ON regexp_replace(UPPER(tam.agency_name),'\\s+',' ','g')
        LIKE regexp_replace(UPPER(COALESCE(NULLIF(t.agency_name,''),'')), '\\s+',' ','g') || '%%'
    WHERE t.net_due > 0
    GROUP BY t.party_name HAVING COUNT(*) > 1
    ORDER BY cnt DESC LIMIT 10
""")
print("\nParties with duplicate JOIN rows:")
for r in cur.fetchall():
    print(f"  {r[0]} → {r[1]} rows")

cur.close()
conn.close()
