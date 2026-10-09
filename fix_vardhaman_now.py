import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Check what's in tally_agency_master for VARDHAMAN
cur.execute("SELECT agency_name, mobile FROM tally_agency_master WHERE agency_name ILIKE '%VARDHAMAN%'")
print("tally_agency_master:")
for r in cur.fetchall():
    print(f"  {r[0]!r} → {r[1]}")

# Check tickets
cur.execute("SELECT agency_name FROM tickets WHERE agency_name ILIKE '%VARDHAMAN%' LIMIT 3")
print("\ntickets:")
for r in cur.fetchall():
    print(f"  {r[0]!r}")

# Force update to full name
cur.execute("""UPDATE tickets SET agency_name='VARDHAMAN AGENCY (JITUBHAI)'
               WHERE agency_name ILIKE 'VARDHAMAN AGENCY%'""")
conn.commit()
print(f"\nUpdated: {cur.rowcount}")

# Add to manual override
cur.execute("""INSERT INTO manual_agency_override(party_name, agency_name)
               SELECT party_name, 'VARDHAMAN AGENCY (JITUBHAI)'
               FROM tickets WHERE agency_name='VARDHAMAN AGENCY (JITUBHAI)'
               ON CONFLICT(party_name) DO UPDATE SET agency_name=EXCLUDED.agency_name""")
conn.commit()
print(f"Overrides: {cur.rowcount}")
cur.close()
conn.close()
