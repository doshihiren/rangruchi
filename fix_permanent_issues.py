import psycopg2, ast, re
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Fix 1: tally_agency_master - keep only first mobile number (before / or ,)
print("[1] Fixing agency mobile - keep first number only...")
cur.execute("SELECT agency_name, mobile FROM tally_agency_master WHERE mobile LIKE '%%/%%' OR mobile LIKE '%%,%%'")
rows = cur.fetchall()
print(f"  Found {len(rows)} agencies with multiple mobiles")
for agency, mobile in rows:
    first = re.split(r'[/,]', mobile)[0].strip()
    first = re.sub(r'[^0-9]','', first)[-10:]
    cur.execute("UPDATE tally_agency_master SET mobile=%s WHERE agency_name=%s", (first, agency))
conn.commit()
print(f"  Fixed {len(rows)} agencies")

# Fix 2: MEM SAAB agency
cur.execute("UPDATE manual_agency_override SET agency_name='SHREE AGENCY (ASHOKBHAI)' WHERE party_name='MEM SAAB LIFE STYLE (AHILYANAGAR)'")
cur.execute("UPDATE tickets SET agency_name='SHREE AGENCY (ASHOKBHAI)' WHERE party_name='MEM SAAB LIFE STYLE (AHILYANAGAR)'")
conn.commit()
print("[2] MEM SAAB → SHREE AGENCY (ASHOKBHAI) ✅")

# Fix 3: Check RADHE RADHE (NASIK) duplicate rows in tickets
cur.execute("SELECT COUNT(*) FROM tickets WHERE party_name='RADHE RADHE (NASIK)'")
print(f"\n[3] RADHE RADHE (NASIK) rows in tickets: {cur.fetchone()[0]}")

cur.close()
conn.close()
