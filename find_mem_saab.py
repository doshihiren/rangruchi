import re, html

with open("Master.xml","rb") as f:
    raw = f.read()
try: text = raw.decode("utf-16-le", errors="ignore")
except: text = raw.decode("utf-8", errors="ignore")

for m in re.finditer(r'<LEDGER\s+NAME="([^"]+)"[^>]*>', text):
    name = html.unescape(m.group(1).strip())
    if 'MEM' in name.upper() or 'SAAB' in name.upper():
        print(f"Master.xml name: {name}")
