import ast

with open(r"flask_app\routes\admin.py","r",encoding="utf-8") as f:
    code = f.read()

OLD = '''                from sync_tally_master import sync_party_master, sync_agency_fullnames
                sync_party_master("Master.xml")
                sync_agency_fullnames()
                # Apply manual overrides LAST - always wins
                from db import execute as _ex
                _ex("""UPDATE tickets t SET agency_name = mo.agency_name
                        FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")
                # Expand truncated agencies one more time
                _ex(r"""UPDATE tickets t SET agency_name = tam.agency_name
                        FROM tally_agency_master tam'''

# Find exact block
idx = code.find("from sync_tally_master import sync_party_master")
end = code.find("AND LOWER(t.agency_name) NOT IN", idx)
end = code.find(")", end) + 1
print("Block to replace:")
print(repr(code[idx:end+50]))
