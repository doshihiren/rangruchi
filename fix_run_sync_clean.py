import ast

with open(r"flask_app\routes\admin.py","r",encoding="utf-8") as f:
    code = f.read()

# Find and replace entire _run_sync function
OLD = '''    def _run_sync():
        global _sync_state
        _sync_state.update({"running": True, "status": "Syncing from Tally...", "result": ""})
        try:
            from sync_engine import run_full_sync
            results = run_full_sync()
            _sync_state["status"] = "Syncing master data..."
            if os.path.exists("Master.xml"):
                # Run sync_tally_master as script
                import subprocess, sys
                subprocess.run([sys.executable, "sync_tally_master.py", "Master.xml"], 
                               cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                               capture_output=True)
                # Run agency fullnames expansion
                from sync_tally_master import sync_agency_fullnames
                sync_agency_fullnames()
                # Apply manual overrides LAST - always wins
                from db import execute as _ex
                _ex("""UPDATE tickets t SET agency_name = mo.agency_name
                        FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")
                # Expand truncated agencies one more time
                _ex(r"""UPDATE tickets t SET agency_name = tam.agency_name
                        FROM tally_agency_master tam
                        WHERE tam.agency_name LIKE t.agency_name || '%%'
                        AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
                        AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
                        AND LOWER(t.agency_name) NOT IN ('nan','none','null','self','cash')""")
                # Apply manual overrides LAST - always wins
                from db import execute as _ex
                _ex("""UPDATE tickets t SET agency_name = mo.agency_name
                        FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")
                # Expand truncated agencies one more time
                _ex(r"""UPDATE tickets t SET agency_name = tam.agency_name
                        FROM tally_agency_master tam
                        WHERE tam.agency_name LIKE t.agency_name || '%%'
                        AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
                        AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
                        AND LOWER(t.agency_name) NOT IN ('nan','none','null','self','cash')""")
                # Apply manual overrides LAST - always wins
                from db import execute as _ex
                _ex("""UPDATE tickets t SET agency_name = mo.agency_name
                        FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")
                # Expand truncated agencies one more time
                _ex(r"""UPDATE tickets t SET agency_name = tam.agency_name
                        FROM tally_agency_master tam
                        WHERE tam.agency_name LIKE t.agency_name || '%%'
                        AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
                        AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
                        AND LOWER(t.agency_name) NOT IN ('nan','none','null','self','cash')""")
            errors = [f"{k}: {v}" for k,v in results.items() if str(v).startswith("ERROR")]
            _sync_state["result"] = (
                f"Done with warnings: {'; '.join(errors[:2])}" if errors else
                f"Sync complete! Outstanding:{results.get('outstanding','?')} | Billwise:{results.get('billwise','?')}"
            )
            _sync_state["status"] = "done"
        except Exception as e:
            _sync_state["result"] = f"Sync error: {e}"
            _sync_state["status"] = "error"
        finally:
            _sync_state["running"] = False
            try: _sync_lock.release()
            except: pass'''

NEW = '''    def _run_sync():
        global _sync_state
        _sync_state.update({"running": True, "status": "Syncing from Tally...", "result": ""})
        try:
            from sync_engine import run_full_sync
            results = run_full_sync()

            # Sync Master.xml
            if os.path.exists("Master.xml"):
                _sync_state["status"] = "Syncing master data..."
                import subprocess, sys
                subprocess.run([sys.executable, "sync_tally_master.py", "Master.xml"],
                               cwd=os.getcwd(), capture_output=True)

            # Expand truncated agency names
            _sync_state["status"] = "Expanding agency names..."
            from db import execute as _ex
            _ex(r"""UPDATE tickets t SET agency_name = tam.agency_name
                    FROM tally_agency_master tam
                    WHERE tam.agency_name LIKE t.agency_name || '%%'
                    AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
                    AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
                    AND LOWER(t.agency_name) NOT IN ('nan','none','null')""")

            # Apply manual overrides LAST
            _ex("""UPDATE tickets t SET agency_name = mo.agency_name
                    FROM manual_agency_override mo WHERE t.party_name = mo.party_name""")

            errors = [f"{k}: {v}" for k,v in results.items() if str(v).startswith("ERROR")]
            _sync_state["result"] = (
                f"Done with warnings: {'; '.join(errors[:2])}" if errors else
                f"Sync complete! Outstanding:{results.get('outstanding','?')} | Billwise:{results.get('billwise','?')}"
            )
            _sync_state["status"] = "done"
        except Exception as e:
            _sync_state["result"] = f"Sync error: {e}"
            _sync_state["status"] = "error"
        finally:
            _sync_state["running"] = False
            try: _sync_lock.release()
            except: pass'''

if OLD in code:
    code = code.replace(OLD, NEW)
    try:
        ast.parse(code)
        with open(r"flask_app\routes\admin.py","w",encoding="utf-8") as f:
            f.write(code)
        print("Fixed: _run_sync cleaned up, no duplicates")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS")
