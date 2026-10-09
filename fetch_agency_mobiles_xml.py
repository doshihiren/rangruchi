import re, html, psycopg2

with open("Master.xml","rb") as f: raw = f.read()
try: text = raw.decode("utf-16-le", errors="ignore")
except: text = raw.decode("utf-8", errors="ignore")

DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

cur.execute("SELECT agency_name, mobile FROM tally_agency_master ORDER BY agency_name")
existing = {r[0]: r[1] for r in cur.fetchall()}

found = missing = updated = 0
print(f"\n{'AGENCY':<50} {'TALLY MOBILE':<15} {'STATUS'}")
print("-"*80)

# Search GROUP blocks for agency mobiles
for m in re.finditer(r'<GROUP\s+NAME="([^"]+)"[^>]*>(.*?)</GROUP>', text, re.DOTALL):
    name  = html.unescape(m.group(1).strip())
    block = m.group(2)

    if name not in existing:
        continue

    mob = re.search(r'(?i)BGRPBROKERGROUPMOUDF[^>]*>(.*?)<', block)
    if mob and mob.group(1).strip():
        mobile = re.sub(r'[^0-9]', '', mob.group(1).strip())[-10:]
        if len(mobile) == 10:
            cur.execute("UPDATE tally_agency_master SET mobile=%s WHERE agency_name=%s", (mobile, name))
            status = "UPDATED" if not existing[name] else "SAME" if existing[name]==mobile else "CHANGED"
            print(f"  {name:<50} {mobile:<15} {status}")
            found += 1
            if status in ("UPDATED","CHANGED"): updated += 1
        else:
            missing += 1
    else:
        missing += 1

conn.commit()
print(f"\nFound: {found} | Missing: {missing} | Updated: {updated}")

# Show still missing
print("\n=== Still no mobile in Tally ===")
cur.execute("SELECT agency_name FROM tally_agency_master WHERE mobile IS NULL OR mobile='' ORDER BY agency_name")
for r in cur.fetchall():
    print(f"  {r[0]}")

cur.close()
conn.close()
