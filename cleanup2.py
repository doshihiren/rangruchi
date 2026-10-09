import os, glob
os.chdir(r"D:\Followup\Project")

to_delete = []
# Root temp files
for pat in ["*.bak","*.bak*","check_*.py","debug_*.py","fix_*.py",
            "test_*.py","show_*.py","run_agency*.py","check_netdue.py",
            "check_party_detail.py","admin_*.html","update_net_due_old.py",
            "list_root_files.py","cleanup_files.py","cleanup_project.py",
            "check_3issues.py","check_tally_agency*.py","check_manual*.py",
            "check_agency*.py","check_inon*.py","debug_inon*.py",
            "check_missing*.py","check_oswal*.py","check_tickets*.py",
            "fix_direct*.py","fix_madhur*.py","fix_tpm*.py",
            "fix_tam*.py","fix_main*.py","fix_3issues*.py",
            "fix_jaibhawani*.py","fix_post_sync*.py","fix_sync_agency*.py",
            "import_pdc*.py","check_pdc*.py","fix_pdc*.py",
            "tally_dump.xml","pdc_*.py","probe_pdc*.py",
            "fetch_pdc*.py","voucher_types.py"]:
    to_delete.extend(glob.glob(pat))

# Flask app bak files
for pat in ["*.bak","*.bak*"]:
    to_delete.extend(glob.glob(f"flask_app/**/{pat}", recursive=True))

to_delete = sorted(set(f for f in to_delete if os.path.isfile(f)))
print(f"To delete: {len(to_delete)}")
for f in to_delete: print(f"  {f}")

import sys
if '--delete' in sys.argv:
    n = 0
    for f in to_delete:
        try: os.remove(f); n+=1
        except: pass
    print(f"Deleted {n}")
