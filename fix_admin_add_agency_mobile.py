import ast

with open(r"flask_app\routes\admin.py","r",encoding="utf-8") as f:
    code = f.read()

OLD = '''            # Apply manual overrides LAST
            _ex("""UPDATE tickets t SET agency_name = mo.agency_name
                    FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")'''

NEW = '''            # Sync agency mobiles from Master.xml
            try:
                from auto_agency_mobile_sync import sync_agency_mobiles
                sync_agency_mobiles()
            except Exception as _ame:
                pass

            # Apply manual overrides LAST
            _ex("""UPDATE tickets t SET agency_name = mo.agency_name
                    FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")'''

if OLD in code:
    code = code.replace(OLD, NEW)
    try:
        ast.parse(code)
        with open(r"flask_app\routes\admin.py","w",encoding="utf-8") as f:
            f.write(code)
        print("Fixed: agency mobiles sync added to Tally Sync button")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS")
    idx = code.find("manual_agency_override mo WHERE")
    print(repr(code[max(0,idx-50):idx+100]))
