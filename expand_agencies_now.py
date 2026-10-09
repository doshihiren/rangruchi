import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Expand truncated agency names
cur.execute(r"""
    UPDATE tickets t SET agency_name = tam.agency_name
    FROM tally_agency_master tam
    WHERE tam.agency_name LIKE t.agency_name || '%%'
    AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
    AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
    AND LOWER(t.agency_name) NOT IN ('nan','none','null')
""")
conn.commit()
print(f"Expanded: {cur.rowcount}")

# Apply manual overrides
cur.execute("UPDATE tickets t SET agency_name=mo.agency_name FROM manual_agency_override mo WHERE t.party_name=mo.party_name")
conn.commit()
print(f"Overrides: {cur.rowcount}")

# Verify problem parties
for p in ['M S RAMAYYA','UNIQUE HANDLOOM','PRADEEP SAREES KADPA','SARATHAS']:
    cur.execute("SELECT t.party_name, t.agency_name, tam.mobile FROM tickets t LEFT JOIN tally_agency_master tam ON tam.agency_name=t.agency_name WHERE t.party_name ILIKE %s LIMIT 1", (f"%{p}%",))
    r = cur.fetchone()
    if r: print(f"  {r[0][:35]} | {r[1]} | {r[2]}")

cur.close()
conn.close()
