with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    lines = f.readlines()

# Fix lines 350-352
print("Before:")
for i in range(349, 353):
    print(f"{i+1}: {lines[i].rstrip()}")

lines[349] = "        LEFT JOIN LATERAL (\n"
lines[350] = "            SELECT mobile FROM tally_agency_master\n"
lines[351] = "            WHERE UPPER(agency_name) LIKE UPPER(COALESCE(NULLIF(t.agency_name,''),NULLIF(tpm.agency_name,''))) || '%'\n"
lines[352] = "            AND mobile IS NOT NULL AND mobile != '' ORDER BY LENGTH(agency_name) ASC LIMIT 1\n"
# Insert closing ) tam after line 352
lines.insert(353, "        ) tam ON TRUE\n")

print("\nAfter:")
for i in range(349, 355):
    print(f"{i+1}: {lines[i].rstrip()}")

import ast
code = ''.join(lines)
try:
    ast.parse(code)
    with open(r"flask_app\routes\tickets.py","w",encoding="utf-8") as f:
        f.write(code)
    print("\nSaved!")
except SyntaxError as e:
    print(f"ERROR line {e.lineno}: {e.msg}")
