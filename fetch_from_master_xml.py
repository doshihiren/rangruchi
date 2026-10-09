import re, html, psycopg2

print("Reading Master.xml...")
with open("Master.xml","rb") as f:
    raw = f.read()
try: text = raw.decode("utf-16-le", errors="ignore")
except: text = raw.decode("utf-8", errors="ignore")
print(f"Size: {len(text):,} chars")

parties = [
    'YOGESH TRADING COMPANY',
    'RAJA INTERNATIONAL LIFESTYLE PRIVATE LIMITED (MZFR)',
    'RADHE RADHE ENTERPRISES',
    'ANAPURNA SALES',
    'JAI BHAWANI TRADING',
    'GH ENTERPRISES INC',
    'RAJA TEX (DALTOGANJ)',
    'MTA TEXTILE AGENCY',
    'SHUBHAM PRAKASH JAIN',
    'ACADEMY FOR COMPUTER SOLUTIONS',
    'KHUSHBHU DEVI SUKESH',
    'THE CHENNAI SILKS',
    'SHYAMA SHYAM FABRICS PVT LTD',
]

DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

print(f"\n{'PARTY':<55} AGENCY")
print("-"*85)

found = 0
for m in re.finditer(r'<LEDGER\s+NAME="([^"]+)"[^>]*>(.*?)</LEDGER>', text, re.DOTALL):
    name  = html.unescape(m.group(1).strip())
    block = m.group(2)

    matched = None
    for p in parties:
        if p.upper() == name.upper() or p.upper()[:30] == name.upper()[:30]:
            matched = p
            break
    if not matched:
        continue

    # Case-insensitive, NO self-ref check - use exact value from Tally
    agency = re.search(r'(?i)BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)<', block)
    ag = html.unescape(agency.group(1).strip()) if agency else ''

    ag_display = ag if ag else 'EMPTY IN TALLY'
    print(f"  {name[:53]:<55} {ag_display}")
    found += 1

    if ag:
        cur.execute("UPDATE tickets SET agency_name=%s WHERE party_name=%s", (ag, matched))
        cur.execute("""INSERT INTO manual_agency_override(party_name,agency_name)
                       VALUES(%s,%s) ON CONFLICT(party_name)
                       DO UPDATE SET agency_name=EXCLUDED.agency_name""", (matched, ag))
        print(f"    Saved to DB")

print(f"\nFound {found}/{len(parties)} parties")
conn.commit()
cur.close()
conn.close()
