import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Direct update for these 9 specific parties
updates = [
    ('VARDHAMAN AGENCY (JITUBHAI)', 'VARDHAMAN AGENCY (JITUBHAI)'),
    ('MUKESH TEXTILE AGENCY', 'MUKESH TEXTILE AGENCY (PRAVINBHAI)'),
    ('R B TEXTILE AGENCY', 'R B TEXTILE AGENCY (BHAGWAT SINGHJI)'),
    ('MAHARAJA AGENCY', 'MAHARAJA AGENCY (RAJESH JI)'),
]

for short, full in updates:
    cur.execute("UPDATE tickets SET agency_name=%s WHERE agency_name=%s", (full, short))
    print(f"Updated {cur.rowcount}: {short} → {full}")

conn.commit()

# Verify
for p in ['M S RAMAYYA','UNIQUE HANDLOOM','PRADEEP SAREES KADPA','SARATHAS']:
    cur.execute("""SELECT t.party_name, t.agency_name, tam.mobile 
                   FROM tickets t 
                   LEFT JOIN tally_agency_master tam ON tam.agency_name=t.agency_name 
                   WHERE t.party_name ILIKE %s LIMIT 1""", (f"%{p}%",))
    r = cur.fetchone()
    if r: print(f"  {r[0][:35]} | {r[1]} | mobile={r[2]}")

cur.close()
conn.close()
