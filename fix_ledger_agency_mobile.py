import ast

with open(r"flask_app\routes\ledger.py","r",encoding="utf-8") as f:
    code = f.read()

OLD = '''            tam = query_df(
                "SELECT mobile FROM tally_agency_master WHERE "
                "regexp_replace(UPPER(agency_name),'\\\\s+',' ','g')=regexp_replace(UPPER(%s),'\\\\s+',' ','g')",
                (agency_nm,))'''

NEW = '''            tam = query_df(
                "SELECT mobile FROM tally_agency_master WHERE "
                "UPPER(agency_name) LIKE UPPER(%s) || '%%' "
                "AND mobile IS NOT NULL AND mobile != '' "
                "ORDER BY LENGTH(agency_name) ASC LIMIT 1",
                (agency_nm,))'''

if OLD in code:
    code = code.replace(OLD, NEW)
    try:
        ast.parse(code)
        with open(r"flask_app\routes\ledger.py","w",encoding="utf-8") as f:
            f.write(code)
        print("Fixed: ledger.py uses LIKE for agency mobile lookup")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS")
    idx = code.find("tally_agency_master WHERE")
    print(repr(code[max(0,idx-20):idx+150]))
