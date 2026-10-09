with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    code = f.read()

OLD = "tally_agency_master tam ON regexp_replace(UPPER(tam.agency_name),'\\\\s+',' ','g')=regexp_replace(UPPER(COALESCE(NULLIF(t.agency_name,''),NULLIF(tpm.agency_name,''))),'\\\\s+',' ','g')"

NEW = """LATERAL (
            SELECT mobile FROM tally_agency_master
            WHERE regexp_replace(UPPER(agency_name),'\\\\s+',' ','g')
                LIKE regexp_replace(UPPER(COALESCE(NULLIF(t.agency_name,''),NULLIF(tpm.agency_name,''))),'\\\\s+',' ','g') || '%%'
            AND mobile IS NOT NULL AND mobile != ''
            ORDER BY LENGTH(agency_name) ASC LIMIT 1
        ) tam"""

if OLD in code:
    code = code.replace(OLD, NEW)
    import ast
    try:
        ast.parse(code)
        with open(r"flask_app\routes\tickets.py","w",encoding="utf-8") as f:
            f.write(code)
        print("FIXED")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS - searching...")
    idx = code.find("tally_agency_master tam")
    print(repr(code[idx:idx+200]))
