import ast, re

with open("sync_tally_master.py","r",encoding="utf-8") as f:
    code = f.read()

OLD = '    agency_mobile = getudf("BGRPBROKERGROUPMOUDF", block)\n    if agency_name and agency_mobile:\n        agencies[agency_name] = {"mobile": agency_mobile, "contact_person": None}'

NEW = '''    agency_mobile_raw = getudf("BGRPBROKERGROUPMOUDF", block)
    # Keep first number only (before / or ,)
    if agency_mobile_raw:
        agency_mobile = re.sub(r'[^0-9]','', re.split(r'[/,]', agency_mobile_raw)[0].strip())[-10:]
    else:
        agency_mobile = ""
    if agency_name and agency_mobile:
        agencies[agency_name] = {"mobile": agency_mobile, "contact_person": None}'''

if OLD in code:
    # Add import re if not present
    if 'import re' not in code:
        code = 'import re\n' + code
    code = code.replace(OLD, NEW)
    try:
        ast.parse(code)
        with open("sync_tally_master.py","w",encoding="utf-8") as f:
            f.write(code)
        print("Fixed: agency mobile keeps first number only on every sync")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS")
    idx = code.find("BGRPBROKERGROUPMOUDF")
    print(repr(code[max(0,idx-50):idx+200]))
