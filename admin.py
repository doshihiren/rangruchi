from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_app.routes.auth import login_required
from db import query_df, execute, fetchone
import hashlib

admin_bp = Blueprint("admin", __name__)
hp = lambda p: hashlib.sha256(p.encode()).hexdigest()

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "Owner":
            flash("Access denied.", "error")
            return redirect(url_for("home.dashboard"))
        return f(*args, **kwargs)
    return decorated

@admin_bp.route("/admin")
@login_required
@admin_required
def admin():
    users    = query_df("SELECT id,username,role,tally_name,email,is_active,created_at FROM users ORDER BY role,username").to_dict("records")
    assigns  = query_df("SELECT * FROM salesperson_mapping ORDER BY agent_name,party_name LIMIT 100").to_dict("records")
    sync_log = query_df("SELECT * FROM sync_log ORDER BY synced_at DESC LIMIT 20").to_dict("records")
    settings = {}
    try:
        s = query_df("SELECT key, value FROM app_settings")
        settings = dict(zip(s['key'], s['value']))
    except Exception:
        pass
    return render_template("admin.html", users=users, settings=settings, assigns=assigns,
        sync_log=sync_log, no_credit=[], call_counts={}, role=session.get("role",""),
        agency_total=0, agency_with_mobile=0, agency_missing=[],
        credit_total=0, credit_with_period=0, credit_missing=[])

@admin_bp.route("/admin/add-user", methods=["POST"])
@login_required
@admin_required
def add_user():
    f = request.form
    try:
        execute("INSERT INTO users(username,password,role,tally_name,email) VALUES(%s,%s,%s,%s,%s)",
            (f["username"],hp(f["password"]),f["role"],f.get("tally_name",""),f.get("email","")))
        flash(f"User {f['username']} created!", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("admin.admin"))

@admin_bp.route("/admin/reset-password", methods=["POST"])
@login_required
@admin_required
def reset_password():
    f = request.form
    execute("UPDATE users SET password=%s WHERE username=%s", (hp(f["password"]),f["username"]))
    flash(f"Password reset for {f['username']}!", "success")
    return redirect(url_for("admin.admin"))

@admin_bp.route("/admin/save-settings", methods=["POST"])
@login_required
def save_settings():
    f = request.form
    try:
        for key in ["priority_high", "priority_mid"]:
            val = f.get(key, "").strip()
            if val and val.isdigit():
                execute("UPDATE app_settings SET value=%s, updated_at=NOW() WHERE key=%s", (val, key))
        flash("Settings saved!", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("admin.admin"))

# ── Sync state ──────────────────────────────────────────────────────────────
import threading as _threading
_sync_lock  = _threading.Lock()
_sync_state = {"running": False, "status": "idle", "result": ""}

@admin_bp.route("/admin/sync-status")
@login_required
def sync_status():
    from flask import jsonify
    return jsonify(_sync_state)

# ── Tally Sync ───────────────────────────────────────────────────────────────
@admin_bp.route("/admin/sync", methods=["POST"])
@login_required
@admin_required
def trigger_sync():
    import threading, os
    global _sync_state
    if not _sync_lock.acquire(blocking=False):
        flash("Sync already running, please wait...", "warning")
        return redirect(url_for("admin.admin"))

    def _run_sync():
        global _sync_state
        _sync_state.update({"running": True, "status": "Syncing from Tally...", "result": ""})
        try:
            from sync_engine import run_full_sync
            results = run_full_sync()
            _sync_state["status"] = "Syncing master data..."
            if os.path.exists("Master.xml"):
                from sync_tally_master import sync_party_master, sync_agency_fullnames
                sync_party_master("Master.xml")
                sync_agency_fullnames()
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
            except: pass

    _threading.Thread(target=_run_sync, daemon=True).start()
    flash("Sync started in background.", "info")
    return redirect(url_for("admin.admin"))

# ── PDC Sync from pdc\pdc.xml (voucher format) ───────────────────────────────
@admin_bp.route("/admin/sync-pdc", methods=["POST"])
@login_required
@admin_required
def trigger_pdc_sync():
    import threading, os, re
    import xml.etree.ElementTree as ET
    from datetime import date as _d
    from db import get_conn, release_conn
    global _sync_state

    PDC_XML_PATH = r"D:\Followup\Project\pdc\pdc.xml"

    def _clean(p):
        return re.sub(r'\s*\(RR\d+\)\s*$','',p).strip()

    def _run_pdc():
        global _sync_state
        _sync_state.update({"running": True, "status": "Importing PDC from XML...", "result": ""})
        try:
            if not os.path.exists(PDC_XML_PATH):
                _sync_state.update({"result": f"ERROR: not found: {PDC_XML_PATH}", "status": "error"})
                return

            with open(PDC_XML_PATH,"rb") as f:
                raw = f.read()
            try:    text = raw.decode("utf-16", errors="ignore")
            except: text = raw.decode("utf-8",  errors="ignore")

            text = text.replace("UDF:","UDF_")
            text = re.sub(r"&#[0-9]+;","",text)
            text = text.replace("ALLLEDGERENTRIES.LIST","ALLLEDGERENTRIES")
            text = text.replace("BILLALLOCATIONS.LIST","BILLALLOCATIONS")
            text = text.replace("BANKALLOCATIONS.LIST","BANKALLOCATIONS")

            root     = ET.fromstring(text)
            vouchers = root.findall(".//VOUCHER")

            records = []
            for v in vouchers:
                party = _clean(v.findtext("PARTYLEDGERNAME","") or "")
                vno   = (v.findtext("VOUCHERNUMBER","") or "").strip()
                dt    = (v.findtext("DATE","") or "").strip()
                vdate = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}" if len(dt)==8 else None

                amt=0; inst_dt=""; chq_no=""; bank=""; bills=[]

                for ale in v.findall("ALLLEDGERENTRIES"):
                    if not party:
                        pf = (ale.findtext("PAYMENTFAVOURING","") or "").strip()
                        if pf: party = _clean(pf)
                    for bk in ale.findall("BANKALLOCATIONS"):
                        pd = (bk.findtext("PDCACTUALDATE","") or bk.findtext("INSTRUMENTDATE","") or "").strip()
                        if pd and len(pd)==8:
                            inst_dt = f"{pd[:4]}-{pd[4:6]}-{pd[6:8]}"
                        chq_no = (bk.findtext("INSTRUMENTNUMBER","") or chq_no).strip()
                        bank   = (bk.findtext("BANKNAME","") or bank).strip()
                        a = abs(float(bk.findtext("AMOUNT","0") or 0))
                        if a: amt = a
                    for ba in ale.findall("BILLALLOCATIONS"):
                        bn = (ba.findtext("NAME","") or "").strip()
                        if bn: bills.append(bn)

                cheque_dt = vdate
                if inst_dt and vdate:
                    try:
                        if _d.fromisoformat(inst_dt) >= _d.fromisoformat(vdate):
                            cheque_dt = inst_dt
                    except: pass

                if party and vno and cheque_dt and amt:
                    records.append((party, vno, cheque_dt, amt, ", ".join(bills),
                                    "Post Dated Receipt", chq_no, bank, vdate))

            conn = get_conn()
            cur  = conn.cursor()
            cur.execute("DELETE FROM pdc_entries")
            for r in records:
                cur.execute("""INSERT INTO pdc_entries
                    (party_name,voucher_number,cheque_date,amount,narration,
                     voucher_type,instrument_number,bank_name,voucher_date)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (voucher_number,party_name,cheque_date)
                    DO UPDATE SET amount=EXCLUDED.amount""", r)

            # Recalculate net_due
            _sync_state["status"] = "Recalculating net due..."
            cur.execute("""
                UPDATE tickets t SET net_due = GREATEST(0,
                    COALESCE((SELECT SUM(b.pending_amount) FROM billwise b
                        WHERE b.party_name=t.party_name AND b.pending_amount>0
                        AND b.invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
                        AND TO_DATE(b.invoice_date,'DD-Mon-YY') <=
                        CURRENT_DATE - MAKE_INTERVAL(days=>COALESCE(NULLIF(t.credit_days,'')::int,30))
                    ),0)
                    - COALESCE((SELECT SUM(p.amount) FROM pdc_entries p WHERE p.party_name=t.party_name),0)
                )
            """)
            conn.commit()
            cur.close()
            release_conn(conn)

            total = sum(r[3] for r in records)
            _sync_state["result"]  = f"PDC Import: {len(records)} entries | Rs {total:,.0f}"
            _sync_state["status"]  = "done"

        except Exception as e:
            _sync_state["result"] = f"PDC Error: {e}"
            _sync_state["status"] = "error"
        finally:
            _sync_state["running"] = False
            try: _sync_lock.release()
            except: pass

    if not _sync_lock.acquire(blocking=False):
        flash("Sync already running, please wait...", "warning")
        return redirect(url_for("admin.admin"))

    _threading.Thread(target=_run_pdc, daemon=True).start()
    flash("PDC import started...", "info")
    return redirect(url_for("admin.admin"))
