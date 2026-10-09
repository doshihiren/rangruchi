with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    code = f.read()

# Find exact string in file
idx = code.find("tally_agency_master tam ON")
end = code.find("'g')", idx) + 4
old = code[idx:end]
print("Found:")
print(repr(old))

new = """LATERAL (
            SELECT mobile FROM tally_agency_master
            WHERE UPPER(agency_name) LIKE UPPER(COALESCE(NULLIF(t.agency_name,''),NULLIF(tpm.agency_name,''))) || '%%'
            AND mobile IS NOT NULL AND mobile != ''
            ORDER BY LENGTH(agency_name) ASC LIMIT 1
        ) tam"""

code = code[:idx] + new + code[end:]

import ast
try:
    ast.parse(code)
    with open(r"flask_app\routes\tickets.py","w",encoding="utf-8") as f:
        f.write(code)
    print("FIXED")
except SyntaxError as e:
    print(f"ERROR: {e.lineno}: {e.msg}")
