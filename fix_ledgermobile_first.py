import ast

with open("sync_engine.py","r",encoding="utf-8") as f:
    code = f.read()

OLD = '                mobile  = led.findtext("LEDGERMOBILE","").strip()'
NEW = '''                # Keep first mobile number only (Tally sometimes stores multiple)
                _mob_raw = led.findtext("LEDGERMOBILE","").strip() or led.findtext("PHONENUMBER","").strip()
                if _mob_raw:
                    import re as _re
                    mobile = _re.sub(r'[^0-9]','', _re.split(r'[/,]', _mob_raw)[0].strip())[-10:]
                else:
                    mobile = ""'''

if OLD in code:
    code = code.replace(OLD, NEW)
    try:
        ast.parse(code)
        with open("sync_engine.py","w",encoding="utf-8") as f:
            f.write(code)
        print("Fixed: party mobile keeps first number on every sync")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS")
