import sys, psycopg2
sys.argv = ['x', 'Master.xml']

DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Step 1: Expand truncated agency names
cur.execute(r"""
    UPDATE tickets t SET agency_name = tam.agency_name
    FROM tally_agency_master tam
    WHERE (tam.agency_name LIKE t.agency_name || '%%'
        OR regexp_replace(UPPER(tam.agency_name),'\\s+',' ','g')
           LIKE regexp_replace(UPPER(t.agency_name),'\\s+',' ','g') || '%%')
    AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
    AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
    AND LOWER(t.agency_name) NOT IN ('nan','none','null')
""")
conn.commit()
print(f"Expanded: {cur.rowcount}")

# Step 2: Copy from tally_party_master
cur.execute(r"""
    UPDATE tickets t SET agency_name = tpm.agency_name
    FROM tally_party_master tpm
    WHERE tpm.party_name = t.party_name
    AND tpm.agency_name IS NOT NULL AND TRIM(tpm.agency_name) != ''
    AND LOWER(tpm.agency_name) NOT IN ('nan','none','null')
    AND LENGTH(tpm.agency_name) >= LENGTH(COALESCE(t.agency_name,''))
""")
conn.commit()
print(f"From tpm: {cur.rowcount}")

# Step 3: Apply manual overrides
cur.execute("""UPDATE tickets t SET agency_name = mo.agency_name
               FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")
conn.commit()
print(f"Overrides: {cur.rowcount}")

# Check SUPER KIDS
cur.execute("SELECT party_name, agency_name FROM tickets WHERE party_name ILIKE '%SUPER KIDS%'")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

cur.close()
conn.close()
print("Done")
