from flask import Blueprint, render_template, session, request, redirect, url_for, flash
from flask_app.routes.auth import login_required
from db import query_df, execute
from datetime import date
import re

tickets_bp = Blueprint("tickets", __name__)

def get_filter():
    role = session.get("role","")
    un   = session.get("username","")
    if role == "Owner": return "", ()
    # All non-owner users see only their assigned parties
    return "WHERE assigned_to=%s", (un,)

def smart_match(text, query):
    if not text or not query:
        return False
    t = str(text).upper().strip()
    q = query.upper().strip()
    if q in t:
        return True
    if q.replace(" ","") in t.replace(" ",""):
        return True
    words = re.split(r"[\s\-&/]+", t)
    initials = "".join(w[0] for w in words if w)
    if q == initials or initials.startswith(q):
        return True
    return False

@tickets_bp.route("/tickets_classic")
@login_required
def tickets():
    wh, wp   = get_filter()
    role     = session.get("role","")
    search   = request.args.get("q","").strip()
    state    = request.args.get("state","All")
    agent    = request.args.get("agent","All")
    agency   = request.args.get("agency","All")
    min_amt  = int(request.args.get("min",0))
    aging    = request.args.get("aging","")
    due7     = request.args.get("due7","")
    status_f = request.args.get("status","")
    assigned = request.args.get("assigned","All")

    # ── Special list modes: due7 / due / unsettled - show specific bills ──
    def _special_list(df, label, badge_class, extra=None):
        total = float(df["pending_amount"].sum()) if not df.empty else 0
        ex = extra or {}
        try:
            s = query_df("SELECT key, value FROM app_settings WHERE key IN ('priority_high','priority_mid')")
            thr = dict(zip(s['key'], s['value'].astype(float)))
            p_high = int(thr.get('priority_high', 100000))
            p_mid  = int(thr.get('priority_mid', 50000))
        except Exception:
            p_high, p_mid = 100000, 50000
        _active_users = query_df("SELECT username, role FROM users WHERE is_active=TRUE ORDER BY username").to_dict("records")
        return render_template("tickets.html",
            tickets=df.to_dict("records") if not df.empty else [],
            total=total, ledger_total=total, unsettled=0.0,
            due_amount=0.0, today_date=date.today().strftime('%d-%b-%Y'),
            states=ex.get("states",[]), agents=[], agencies=ex.get("agencies",[]),
            cities=ex.get("cities",[]),
            active_users=_active_users,
            priority_high=p_high, priority_mid=p_mid,
            role=role, due7_mode=True,
            mode_label=label, mode_badge_class=badge_class,
            filters={"q":request.args.get("q",""),"state":request.args.get("state","All"),
                     "agent":"All","agency":request.args.get("agency","All"),
                     "city":request.args.get("city","All"),
                     "min":int(request.args.get("min",0)),"status":"","assigned":"All"}
        )

    due_param       = request.args.get("due","")
    unsettled_param = request.args.get("unsettled","")

    if due7:
        due_bills = query_df("""
            SELECT b.party_name, t.ticket_number,
                   b.invoice_date AS bill_date,
                   b.invoice_no AS bill_no,
                   b.pending_amount,
                   sm.agent_name, sm.agency_name, sm.seller_name,
                   sm.party_state, sm.party_place, sm.party_mobile,
                   sma.party_mobile AS agency_mobile,
                   (TO_DATE(b.invoice_date,'DD-Mon-YY') + INTERVAL '30 days')::date AS due_date
            FROM billwise b
            LEFT JOIN salesperson_mapping sm ON sm.party_name = b.party_name
            LEFT JOIN salesperson_mapping sma ON UPPER(sma.party_name)=UPPER(sm.agency_name)
            LEFT JOIN tickets t ON t.party_name = b.party_name
            WHERE b.pending_amount > 0
            AND b.invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
            AND (TO_DATE(b.invoice_date,'DD-Mon-YY') + INTERVAL '30 days')::date
                BETWEEN CURRENT_DATE AND CURRENT_DATE + 7
            ORDER BY due_date ASC
        """)
        return _special_list(due_bills, "📅 Bills due in next 7 days (invoice + 30 days)", "bg-green-100 text-green-700")

    if due_param == "1":
        due_bills = query_df("""
            SELECT b.party_name, t.ticket_number,
                   b.invoice_date AS bill_date,
                   b.invoice_no AS bill_no,
                   b.pending_amount,
                   sm.agent_name, sm.agency_name, sm.seller_name,
                   sm.party_state, sm.party_place, sm.party_mobile,
                   sma.party_mobile AS agency_mobile,
                   b.overdue_days AS days_overdue
            FROM billwise b
            LEFT JOIN salesperson_mapping sm ON sm.party_name = b.party_name
            LEFT JOIN salesperson_mapping sma ON UPPER(sma.party_name)=UPPER(sm.agency_name)
            LEFT JOIN tickets t ON t.party_name = b.party_name
            WHERE b.pending_amount > 0
            AND COALESCE(b.overdue_days,0) > 0
            ORDER BY b.overdue_days DESC
        """)
        # Apply filters on due list
        if not due_bills.empty:
            q2 = request.args.get("q","").strip()
            state2 = request.args.get("state","All")
            agency2 = request.args.get("agency","All")
            city2 = request.args.get("city","All")
            min2 = int(request.args.get("min",0))
            if q2:
                due_bills = due_bills[due_bills.apply(lambda r: any(
                    smart_match(str(r.get(f,"")), q2)
                    for f in ["party_name","ticket_number","agency_name","party_mobile"]), axis=1)]
            if state2 != "All":
                due_bills = due_bills[due_bills["party_state"]==state2]
            if agency2 != "All":
                due_bills = due_bills[due_bills["agency_name"]==agency2]
            if city2 != "All":
                due_bills = due_bills[due_bills["party_place"]==city2]
            if min2 > 0:
                due_bills = due_bills[due_bills["pending_amount"]>=min2]
        due_states   = sorted(due_bills["party_state"].dropna().unique().tolist()) if not due_bills.empty else []
        due_agencies = sorted(due_bills["agency_name"].dropna().unique().tolist()) if not due_bills.empty else []
        due_cities   = sorted(due_bills["party_place"].dropna().unique().tolist()) if not due_bills.empty else []
        return _special_list(due_bills, "⚠️ Bills past due date (Tally overdue calculation)",
                             "bg-red-100 text-red-700",
                             extra={"states":due_states,"agencies":due_agencies,"cities":due_cities})

    if unsettled_param == "1":
        unsettled_bills = query_df("""
            SELECT b.party_name, t.ticket_number,
                   b.invoice_no AS bill_no, b.invoice_date AS bill_date,
                   b.pending_amount,
                   sm.agent_name, sm.agency_name, sm.seller_name,
                   sm.party_state, sm.party_place, sm.party_mobile,
                   sma.party_mobile AS agency_mobile
            FROM billwise b
            LEFT JOIN salesperson_mapping sm ON sm.party_name = b.party_name
            LEFT JOIN salesperson_mapping sma ON UPPER(sma.party_name)=UPPER(sm.agency_name)
            LEFT JOIN tickets t ON t.party_name = b.party_name
            WHERE b.pending_amount > 0
            AND b.invoice_no ILIKE '%on account%'
            ORDER BY b.pending_amount DESC
        """)
        return _special_list(unsettled_bills, "💰 Bills marked ON ACCOUNT (not allocated)", "bg-amber-100 text-amber-700")

    # ── Load base tickets - parties with pending bills ──
    # Only show parties where pending > 0 AND net due (pending - PDC) > 0
    # Show only parties with:
    # 1. Overdue bills (past credit period) in billwise
    # 2. Net overdue > PDC
    # Show parties with pending > 0 and net due (pending - PDC) > 0
    # Use pre-calculated net_due (accounts for each party's actual credit period)
    has_bills = "t.net_due > 0"
    extra_wh = wh.replace('WHERE','WHERE t.') if wh else ""
    if extra_wh:
        extra_wh = f"{extra_wh} AND {has_bills}"
    else:
        extra_wh = f"WHERE {has_bills}"

    base = query_df(
        f"SELECT "
        f"t.id, t.bill_no, t.bill_date, t.party_name, t.party_gstin, "
        f"COALESCE(NULLIF(tpm.state,''), t.party_state) AS party_state, "
        f"COALESCE(NULLIF(tpm.place_udf,''), t.party_place) AS party_place, "
        f"COALESCE(NULLIF(tpm.mobile,''), t.party_mobile) AS party_mobile, "
        f"t.party_address, "
        f"t.agent_name, "
        f"COALESCE(NULLIF(tpm.agency_name,''), t.agency_name) AS agency_name, "
        f"t.seller_name, t.credit_days, "
        f"t.taxable_amount, t.tax_amount, t.total_amount, t.pending_amount, "
        f"t.status, t.transporter, t.synced_at, t.ticket_number, "
        f"t.original_amount, t.closed_date, t.escalated, t.escalated_at, t.assigned_to, t.net_due, t.agency_mobile AS t_agency_mobile, "
        f"sm_party.party_place AS sm_city, "
        f"sm_party.agency_mobile AS sm_ag_mob, "
        f"COALESCE(tam.mobile, sm_agency.party_mobile) AS sm_agency_phone "
        f"FROM tickets t "
        f"LEFT JOIN tally_party_master tpm ON tpm.party_name_norm=t.party_name_norm "
        f"LEFT JOIN salesperson_mapping sm_party ON sm_party.party_name=t.party_name "
        f"LEFT JOIN salesperson_mapping sm_agency ON UPPER(sm_agency.party_name)=UPPER(COALESCE(NULLIF(tpm.agency_name,''),t.agency_name)) "
        f"LEFT JOIN LATERAL (SELECT mobile FROM tally_agency_master WHERE UPPER(agency_name) LIKE UPPER(COALESCE(NULLIF(t.agency_name,''),NULLIF(tpm.agency_name,''))) || '%%' AND mobile IS NOT NULL AND mobile != '' ORDER BY LENGTH(agency_name) ASC LIMIT 1) tam "
        f"{extra_wh} "
        f"AND t.pending_amount > 0 ORDER BY "
        f"CASE WHEN t.bill_date ~ '^[0-9]{{2}}-[A-Za-z]{{3}}-[0-9]{{2}}$' "
        f"THEN TO_DATE(t.bill_date,'DD-Mon-YY') ELSE NULL END ASC NULLS LAST, t.pending_amount DESC",
        wp if wp else None
    )

    # Zero net-due filter handled in SQL WHERE clause

    states   = sorted(base["party_state"].dropna().unique().tolist())  if not base.empty else []
    cities   = sorted([x for x in base["sm_city"].dropna().unique().tolist() if str(x) not in ('nan','None','')])  if not base.empty and "sm_city" in base.columns else []
    agents   = sorted(base["agent_name"].dropna().unique().tolist())   if not base.empty and role in ("Owner","Admin") else []
    agencies = sorted(base["agency_name"].dropna().unique().tolist())  if not base.empty and role in ("Owner","Admin","Agent") else []

    # ── Smart universal search ───────────────────────────────────
    if search and not base.empty:
        q = search.upper().strip()
        mask = base.apply(lambda row: (
            smart_match(row.get("party_name",""), q) or
            smart_match(row.get("ticket_number",""), q) or
            smart_match(row.get("bill_no",""), q) or
            smart_match(row.get("agency_name",""), q) or
            smart_match(row.get("agent_name",""), q) or
            smart_match(str(row.get("party_mobile","")), q) or
            smart_match(row.get("party_state",""), q)
        ), axis=1)
        base = base[mask]

    if state  != "All" and not base.empty: base = base[base["party_state"]==state]
    if agent  != "All" and role in ("Owner","Admin") and not base.empty: base = base[base["agent_name"]==agent]
    if agency != "All" and not base.empty: base = base[base["agency_name"]==agency]
    city_f = request.args.get("city","All")
    if city_f != "All" and not base.empty and "sm_city" in base.columns: base = base[base["sm_city"]==city_f]
    if min_amt > 0 and not base.empty: base = base[base["pending_amount"]>=min_amt]
    if status_f and not base.empty and "status" in base.columns:
        base = base[base["status"]==status_f]

    # ── Manual assignment filter ────────────────────────────────────
    if assigned != "All" and not base.empty:
        if assigned == "Unassigned":
            base = base[base["assigned_to"].isna() | (base["assigned_to"]=="")]
        else:
            base = base[base["assigned_to"]==assigned]

    total   = float(base["net_due"].sum()) if not base.empty and "net_due" in base.columns else (float(base["pending_amount"].sum()) if not base.empty else 0)
    # Clean NaN values so template gets None instead of float('nan')
    if not base.empty:
        import numpy as np
        base = base.where(base.notna(), other=None)
    # Clean NaN/nan string values before passing to template
    if not base.empty:
        # Add due bill count per party
        try:
            from db import query_df as _qdf
            _bc = _qdf("""
                SELECT party_name, COUNT(*) AS bill_count
                FROM billwise
                WHERE pending_amount > 0
                AND invoice_date LIKE '__-___-__'
                AND (TO_DATE(invoice_date,'DD-Mon-YY') + INTERVAL '30 days') < CURRENT_DATE
                GROUP BY party_name
            """)
            if not _bc.empty:
                _bc_map = dict(zip(_bc["party_name"], _bc["bill_count"].astype(int)))
                base["bill_count"] = base["party_name"].map(_bc_map).fillna(0).astype(int)
            else:
                base["bill_count"] = 0
        except Exception:
            base["bill_count"] = 0
        base = base.where(base.notna(), other=None)
        # Replace ALL nan-like strings with None
        str_cols = base.select_dtypes(include='object').columns
        base[str_cols] = base[str_cols].replace({'nan': None, 'None': None, '': None})
    records = base.to_dict("records") if not base.empty else []

    # ── Ledger/Due/Unsettled - EXACT same logic as home.py dashboard ──
    try:
        ledger_total = float(query_df("""
            SELECT COALESCE(SUM(pending_amount),0) t FROM billwise WHERE pending_amount > 0
        """).iloc[0]["t"])

        unsettled = float(query_df("""
            SELECT COALESCE(SUM(pending_amount),0) t FROM billwise
            WHERE pending_amount > 0 AND invoice_no ILIKE '%on account%'
        """).iloc[0]["t"])

        due_amount = float(query_df("""
            SELECT COALESCE(SUM(net_due),0) t FROM tickets WHERE net_due > 0
        """).iloc[0]["t"])
    except Exception:
        ledger_total = total
        unsettled = 0.0
        due_amount = 0.0

    active_users = query_df("SELECT username, role FROM users WHERE is_active=TRUE ORDER BY username").to_dict("records")

    # Load priority thresholds
    try:
        s = query_df("SELECT key, value FROM app_settings WHERE key IN ('priority_high','priority_mid')")
        thr = dict(zip(s['key'], s['value'].astype(float)))
        priority_high = int(thr.get('priority_high', 100000))
        priority_mid  = int(thr.get('priority_mid', 50000))
    except Exception:
        priority_high, priority_mid = 100000, 50000

    return render_template("tickets.html",
        tickets=records, total=total,
        priority_high=priority_high, priority_mid=priority_mid,
        due_amount=due_amount,
        today_date=date.today().strftime('%d-%b-%Y'),
        ledger_total=ledger_total, unsettled=unsettled,
        states=states, agents=agents, agencies=agencies, cities=cities,
        active_users=active_users,
        role=role, due7_mode=False,
        filters={"q":search,"state":state,"agent":agent,"agency":agency,"city":request.args.get("city","All"),"min":min_amt,"status":status_f,"assigned":assigned}
    )


@tickets_bp.route("/tickets/escalate", methods=["POST"])
@login_required
def escalate_ticket():
    ticket_id = request.form.get("ticket_id")
    try:
        execute("UPDATE tickets SET escalated=TRUE, escalated_at=NOW() WHERE id=%s", (ticket_id,))
        flash("Ticket escalated to senior management.", "success")
    except Exception as e:
        flash(f"Could not escalate: {e}", "error")
    return redirect(request.referrer or url_for("tickets.tickets"))




@tickets_bp.route("/tickets")
@login_required
def tickets2():
    from datetime import date
    from db import get_conn
    role = session.get("role","")
    un   = session.get("username","")

    MAIN_SQL = """
        SELECT
            t.party_name, t.ticket_number, t.credit_days, t.net_due,
            t.assigned_to, t.party_mobile, t.assigned_on,
            COALESCE(NULLIF(t.agency_name,''), NULLIF(tpm.agency_name,''), '') AS agency_full,
            COALESCE(tam.mobile, '') AS agency_phone,
            COALESCE(p.pdc_total, 0) AS pdc_total,
            COALESCE(db2.due_count, 0) AS due_count,
            COALESCE(db2.max_overdue, 0) AS max_overdue,
            COALESCE(fc.fu_count, 0) AS fu_count
        FROM tickets t
        LEFT JOIN tally_party_master tpm
            ON regexp_replace(UPPER(tpm.party_name),'\s+',' ','g')
             = regexp_replace(UPPER(t.party_name),'\s+',' ','g')
        LEFT JOIN LATERAL (
            SELECT mobile FROM tally_agency_master
            WHERE UPPER(agency_name) LIKE UPPER(COALESCE(NULLIF(t.agency_name,''),NULLIF(tpm.agency_name,''))) || '%%'
            AND mobile IS NOT NULL AND mobile != '' ORDER BY LENGTH(agency_name) ASC LIMIT 1
        ) tam ON TRUE
        LEFT JOIN (
            SELECT party_name, SUM(amount) AS pdc_total
            FROM pdc_entries GROUP BY party_name
        ) p ON p.party_name = t.party_name
        LEFT JOIN (
            SELECT party_name, COUNT(*) AS due_count,
                MAX(EXTRACT(DAY FROM (NOW() - TO_DATE(invoice_date,'DD-Mon-YY')))::int) AS max_overdue
            FROM billwise
            WHERE pending_amount > 0 AND invoice_no NOT ILIKE '%%on account%%'
            AND invoice_date LIKE '__-___-__'
            GROUP BY party_name
        ) db2 ON db2.party_name = t.party_name
        LEFT JOIN (
            SELECT party_name, COUNT(*) AS fu_count
            FROM followups GROUP BY party_name
        ) fc ON fc.party_name = t.party_name
        WHERE t.net_due > 0
    """

    conn2 = get_conn()
    cur2  = conn2.cursor()

    if role == "Owner":
        cur2.execute(MAIN_SQL + " ORDER BY t.net_due DESC")
    else:
        cur2.execute(MAIN_SQL + " AND t.assigned_to=%s ORDER BY t.net_due DESC", (un,))

    cols = [d[0] for d in cur2.description]
    rows_data = [dict(zip(cols, r)) for r in cur2.fetchall()]

    # User summary cards - Owner sees all, others see only own
    if role == "Owner":
        cur2.execute("""
            SELECT t.assigned_to, COUNT(*) cnt, SUM(t.net_due) amt
            FROM tickets t WHERE t.net_due > 0
            AND t.assigned_to IS NOT NULL AND t.assigned_to != ''
            GROUP BY t.assigned_to
            ORDER BY
                CASE WHEN LOWER(t.assigned_to)='owner' THEN 0 ELSE 1 END,
                amt DESC
        """)
    else:
        cur2.execute("""
            SELECT t.assigned_to, COUNT(*) cnt, SUM(t.net_due) amt
            FROM tickets t WHERE t.net_due > 0
            AND t.assigned_to = %s
            GROUP BY t.assigned_to
        """, (un,))
    user_cards = [{"name": r[0], "cnt": r[1], "amt": float(r[2] or 0)} for r in cur2.fetchall()]

    cur2.execute("SELECT COUNT(*), SUM(net_due) FROM tickets WHERE net_due>0 AND (assigned_to IS NULL OR assigned_to='')")
    un_row = cur2.fetchone()
    unassigned_card = {"cnt": un_row[0], "amt": float(un_row[1] or 0)}

    cur2.execute("SELECT username FROM users WHERE is_active=TRUE ORDER BY username")
    active_users = [r[0] for r in cur2.fetchall()]

    cur2.close()
    conn2.close()

    total_net     = sum(float(r['net_due'] or 0) for r in rows_data)
    total_pdc     = sum(float(r['pdc_total'] or 0) for r in rows_data)
    total_parties = len(rows_data)
    unassigned    = sum(1 for r in rows_data if not r.get('assigned_to'))
    no_agency     = sum(1 for r in rows_data if not r.get('agency_full'))
    no_ag_mob     = sum(1 for r in rows_data if r.get('agency_full') and not r.get('agency_phone'))

    return render_template("tickets.html",
        tickets=rows_data, user_cards=user_cards,
        unassigned_card=unassigned_card, active_users=active_users,
        total_net=total_net, total_pdc=total_pdc,
        total_parties=total_parties, unassigned=unassigned,
        no_agency=no_agency, no_ag_mob=no_ag_mob,
        today_date=date.today().strftime("%d-%b-%Y"), role=role,
    )

@tickets_bp.route("/tickets/assign", methods=["POST"])
def tickets2_assign():
    from flask import request as req, jsonify
    if "username" not in session:
        return jsonify({"ok": False, "msg": "Not logged in"}), 401
    role = session.get("role","")
    if role.lower() not in ("owner","admin"):
        return jsonify({"ok": False, "msg": "Not authorized", "role": role}), 403
    party    = req.form.get("party","").strip()
    assignee = req.form.get("assignee","").strip()
    from db import execute
    from datetime import date
    if assignee:
        execute("UPDATE tickets SET assigned_to=%s, assigned_on=%s WHERE party_name=%s",
                (assignee, str(date.today()), party))
    else:
        execute("UPDATE tickets SET assigned_to=NULL, assigned_on=NULL WHERE party_name=%s",
                (party,))
    return jsonify({"ok": True, "party": party, "assignee": assignee})
