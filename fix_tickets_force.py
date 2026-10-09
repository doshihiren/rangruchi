with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    code = f.read()

idx = code.find("tally_agency_master tam ON")
end = idx + 181
old = code[idx:end]
print(f"Replacing: {repr(old[:50])}...")

new = "LATERAL (SELECT mobile FROM tally_agency_master WHERE UPPER(agency_name) LIKE UPPER(COALESCE(NULLIF(t.agency_name,''),NULLIF(tpm.agency_name,''))) || '%%' AND mobile IS NOT NULL AND mobile != '' ORDER BY LENGTH(agency_name) ASC LIMIT 1) tam "

code2 = code[:idx] + new + code[end:]

import ast
try:
    ast.parse(code2)
    with open(r"flask_app\routes\tickets.py","w",encoding="utf-8") as f:
        f.write(code2)
    print("Saved! LATERAL:", "LATERAL" in open(r"flask_app\routes\tickets.py").read())
except SyntaxError as e:
    print(f"SyntaxError line {e.lineno}: {e.msg}")
    lines = code2.split('\n')
    for i in range(max(0,e.lineno-2),min(len(lines),e.lineno+2)):
        print(f"{i+1}: {lines[i]}")
