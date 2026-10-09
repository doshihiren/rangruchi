import ast

with open(r"flask_app\routes\admin.py","r",encoding="utf-8") as f:
    code = f.read()

OLD = '''                from sync_tally_master import sync_party_master, sync_agency_fullnames
                sync_party_master("Master.xml")
                sync_agency_fullnames()'''

NEW = '''                # Run sync_tally_master as script
                import subprocess, sys
                subprocess.run([sys.executable, "sync_tally_master.py", "Master.xml"], 
                               cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                               capture_output=True)
                # Run agency fullnames expansion
                from sync_tally_master import sync_agency_fullnames
                sync_agency_fullnames()'''

if OLD in code:
    code = code.replace(OLD, NEW)
    try:
        ast.parse(code)
        with open(r"flask_app\routes\admin.py","w",encoding="utf-8") as f:
            f.write(code)
        print("Fixed: admin.py uses subprocess for sync_tally_master")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS")
