import re, html, psycopg2

with open("Master.xml","rb") as f: raw = f.read()
try: text = raw.decode("utf-16-le", errors="ignore")
except: text = raw.decode("utf-8", errors="ignore")

# Search for RAJA TEX
for m in re.finditer(r'<LEDGER\s+NAME="([^"]+)"[^>]*>(.*?)</LEDGER>', text, re.DOTALL):
    name = html.unescape(m.group(1).strip())
    if 'RAJA' in name.upper() and 'TEX' in name.upper():
        block = m.group(2)
        agency = re.search(r'(?i)BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)<', block)
        ag = html.unescape(agency.group(1).strip()) if agency else 'EMPTY'
        print(f"  {name} → {ag}")
