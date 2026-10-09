from flask import Blueprint, render_template, session
from flask_app.routes.auth import login_required
from db import query_df
from datetime import date

home_bp = Blueprint("home", __name__)

def get_fu_filter():
    un=session.get("username","")
    # Everyone including Owner sees only their own followups
    return "WHERE EXISTS (SELECT 1 FROM tickets owner_ticket WHERE owner_ticket.party_name=f.party_name AND owner_ticket.assigned_to=%s)",(un,)

def fmt(n):
    n = abs(n or 0)
    s = f"₹{n:,.0f}"
    if n >= 10000000: s += f" ({n/10000000:.2f} Cr)"
    elif n >= 100000: s += f" ({n/100000:.2f} L)"
    return s

@home_bp.route("/dashboard")
@login_required
def dashboard():
    role=session.get("role"); un=session.get("username"); tn=session.get("tally_name")
    fh,fp=get_fu_filter()

    try:
        # ── 1. Total Outstanding ─────────────────────────────────────
        out = float(query_df("""
            SELECT COALESCE(SUM(b.pending_amount),0) t
            FROM billwise b WHERE b.pending_amount > 0
        """).iloc[0]["t"])

        # ── 1b. Due Amount ───────────────────────────────────────────
        due_amount = float(query_df("""
            SELECT COALESCE(SUM(net_due),0) t FROM tickets WHERE net_due > 0
        """).iloc[0]["t"])

        # ── 1c. Unsettled Amount (ON ACCOUNT) ───────────────────────
        unsettled_on_account = float(query_df("""
            SELECT COALESCE(SUM(b.pending_amount),0) t
            FROM billwise b WHERE b.pending_amount > 0
            AND b.invoice_no ILIKE '%on account%'
        """).iloc[0]["t"])

        # ── 1d. Suspense Amount (X A/C) ─────────────────────────────
        suspense_row = query_df("SELECT balance FROM outstanding WHERE party_name = 'X A/C'")
        suspense_amount = float(suspense_row.iloc[0]["balance"]) if not suspense_row.empty else 0.0

        # ── 1e. PDC (Post-Dated Cheques) ────────────────────────────
        pdc_row = query_df("""
            SELECT COUNT(*) cnt, COALESCE(SUM(amount),0) total
            FROM pdc_entries
        """)
        pdc_count  = int(pdc_row.iloc[0]["cnt"])
        pdc_amount = float(pdc_row.iloc[0]["total"])

        # ── 2. Due in next 7 days ────────────────────────────────────
        due7 = float(query_df("""
            SELECT COALESCE(SUM(pending_amount),0) t
            FROM billwise
            WHERE pending_amount > 0
            AND party_name IN (SELECT party_name FROM tickets)
            AND invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
            AND (TO_DATE(invoice_date,'DD-Mon-YY') + INTERVAL '30 days')::date
                BETWEEN CURRENT_DATE AND CURRENT_DATE + 7
        """).iloc[0]["t"])

        # ── 3. Unallocated receipts ──────────────────────────────────
        unalloc_raw = float(query_df("""
            SELECT COALESCE(SUM(GREATEST(b.billwise_total - COALESCE(o.balance,0), 0)),0) t
            FROM (
                SELECT party_name, SUM(pending_amount) AS billwise_total
                FROM billwise WHERE pending_amount > 0
                GROUP BY party_name
            ) b
            JOIN tickets t2 ON t2.party_name = b.party_name
            LEFT JOIN outstanding o ON o.party_name = b.party_name
                AND o.balance > 0
        """).iloc[0]["t"])
        unalloc = fmt(unalloc_raw) if unalloc_raw > 0 else "₹0"

        # ── 4. Follow-ups ────────────────────────────────────────────
        BASE_F = """SELECT f.id, f.party_name, f.bill_no, f.status, f.priority,
            f.next_followup_date, f.last_call_date, f.notes, f.assigned_to,
            t.pending_amount AS outstanding, t.party_mobile,
            t.agent_name, t.agency_name, t.seller_name, t.party_state
            FROM followups f LEFT JOIN tickets t ON t.party_name=f.party_name
            WHERE COALESCE(t.net_due, 0) > 0
            AND (f.archived IS NULL OR f.archived = FALSE)"""

        if fh:
            # get_fu_filter already starts with WHERE — turn into AND append
            fu_and = fh.replace("WHERE ", "AND ", 1)
            w_today    = f"{fu_and} AND f.next_followup_date=CURRENT_DATE AND f.status NOT IN ('Paid','Closed','Dispute')"
            w_missed   = f"{fu_and} AND f.next_followup_date<CURRENT_DATE AND f.status NOT IN ('Paid','Closed','Dispute')"
            w_upcoming = f"{fu_and} AND f.next_followup_date>CURRENT_DATE AND f.next_followup_date<=CURRENT_DATE+7 AND f.status NOT IN ('Paid','Closed','Dispute')"
            p = fp
        else:
            w_today    = "AND f.next_followup_date=CURRENT_DATE AND f.status NOT IN ('Paid','Closed','Dispute')"
            w_missed   = "AND f.next_followup_date<CURRENT_DATE AND f.status NOT IN ('Paid','Closed','Dispute')"
            w_upcoming = "AND f.next_followup_date>CURRENT_DATE AND f.next_followup_date<=CURRENT_DATE+7 AND f.status NOT IN ('Paid','Closed','Dispute')"
            p = None

        today_fu    = query_df(f"{BASE_F} {w_today}    ORDER BY f.priority DESC LIMIT 20", p)
        missed_fu   = query_df(f"{BASE_F} {w_missed}   ORDER BY f.next_followup_date DESC LIMIT 20", p)
        upcoming_fu = query_df(f"{BASE_F} {w_upcoming} ORDER BY f.next_followup_date ASC LIMIT 20", p)

        def get_history(party_name):
            h = query_df("""
                SELECT last_call_date, next_followup_date, status, notes, assigned_to
                FROM followups WHERE party_name=%s ORDER BY created_at DESC LIMIT 5
            """, (party_name,))
            return h.to_dict("records") if not h.empty else []

        today_fu_list    = today_fu.to_dict("records")    if not today_fu.empty    else []
        missed_fu_list   = missed_fu.to_dict("records")   if not missed_fu.empty   else []
        upcoming_fu_list = upcoming_fu.to_dict("records") if not upcoming_fu.empty else []

        for f in today_fu_list + missed_fu_list + upcoming_fu_list:
            f["history"] = get_history(f["party_name"])
            mob = str(f.get("party_mobile") or "")
            f["mobile_display"] = mob[-10:] if len(mob) >= 10 else ""

        # ── 5. Assignment buckets ─────────────────────────────────────
        def assign_bucket(label):
            r = query_df("""
                SELECT COUNT(*) c, COALESCE(SUM(t.net_due),0) amt
                FROM tickets t WHERE t.assigned_to = %s
                AND t.net_due > 0
            """, (label,)).iloc[0]
            return int(r["c"]), float(r["amt"])

        acc_c, acc_a = assign_bucket("Accounts Team")
        sr_c,  sr_a  = assign_bucket("Senior Accountant")
        own_c, own_a = assign_bucket("Owner")

        unassigned_r = query_df("""
            SELECT COUNT(*) c, COALESCE(SUM(t.net_due),0) amt
            FROM tickets t
            WHERE (t.assigned_to IS NULL OR t.assigned_to='')
            AND t.net_due > 0
        """).iloc[0]
        unassigned_c = int(unassigned_r["c"])
        unassigned_a = float(unassigned_r["amt"])

        # ── 5b. Follow-up call counts ─────────────────────────────────
        fu_counts = {}
        for cat in ("Accounts Team","Senior Accountant","Owner"):
            r = query_df("""
                SELECT
                  COUNT(*) FILTER (WHERE f.last_call_date = CURRENT_DATE) AS today_c,
                  COUNT(*) FILTER (WHERE f.last_call_date >= CURRENT_DATE - 7)  AS d7_c,
                  COUNT(*) FILTER (WHERE f.last_call_date >= CURRENT_DATE - 30) AS d30_c,
                  COUNT(*) AS overall_c
                FROM followups f
                JOIN tickets t ON t.party_name = f.party_name
                WHERE t.assigned_to = %s
            """, (cat,)).iloc[0]
            fu_counts[cat] = {
                "today": int(r["today_c"]), "d7": int(r["d7_c"]),
                "d30": int(r["d30_c"]), "overall": int(r["overall_c"]),
            }

        if role == "Owner":
            user_fu = query_df("""
                SELECT f.created_by AS username,
                  COUNT(*) FILTER (WHERE f.last_call_date = CURRENT_DATE) AS today_c,
                  COUNT(*) FILTER (WHERE f.last_call_date >= CURRENT_DATE - 7)  AS d7_c,
                  COUNT(*) FILTER (WHERE f.last_call_date >= CURRENT_DATE - 30) AS d30_c,
                  COUNT(*) AS overall_c
                FROM followups f
                WHERE f.created_by IS NOT NULL AND f.created_by != ''
                GROUP BY f.created_by ORDER BY overall_c DESC
            """)
        else:
            user_fu = query_df("""
                SELECT f.created_by AS username,
                  COUNT(*) FILTER (WHERE f.last_call_date = CURRENT_DATE) AS today_c,
                  COUNT(*) FILTER (WHERE f.last_call_date >= CURRENT_DATE - 7)  AS d7_c,
                  COUNT(*) FILTER (WHERE f.last_call_date >= CURRENT_DATE - 30) AS d30_c,
                  COUNT(*) AS overall_c
                FROM followups f
                WHERE f.created_by = %s
                GROUP BY f.created_by ORDER BY overall_c DESC
            """, (un,))
        user_fu_list = user_fu.to_dict('records') if not user_fu.empty else []

        # ── 6. Top outstanding parties ────────────────────────────────
        top = query_df("""
            SELECT o.party_name, ABS(o.balance) AS balance,
                   sm.agent_name, sm.agency_name, sm.seller_name,
                   sm.party_state, COALESCE(sm.party_mobile,'') AS party_mobile
            FROM outstanding o
            LEFT JOIN salesperson_mapping sm ON sm.party_name=o.party_name
            WHERE o.balance != 0
            AND EXISTS(SELECT 1 FROM tickets t WHERE t.party_name=o.party_name)
            ORDER BY ABS(o.balance) DESC LIMIT 10
        """)

        sync = query_df("SELECT * FROM sync_log ORDER BY synced_at DESC LIMIT 1")
        last_sync = sync.iloc[0].to_dict() if not sync.empty else None

        # Active users for dynamic responsibility cards
        active_users = query_df("SELECT username, role FROM users WHERE is_active=TRUE ORDER BY role DESC, username ASC").to_dict("records")

        # Per-user ticket counts
        uc = query_df("""
            SELECT t.assigned_to, COUNT(*) cnt, COALESCE(SUM(t.net_due),0) amt
            FROM tickets t
            WHERE t.assigned_to IS NOT NULL AND t.assigned_to != ''
            AND t.net_due > 0
            GROUP BY t.assigned_to
        """)
        user_ticket_counts = {row['assigned_to']: {'cnt': int(row['cnt']), 'amt': float(row['amt'])} for _, row in uc.iterrows()} if not uc.empty else {}

        try:
            s = query_df("SELECT key, value FROM app_settings WHERE key IN ('priority_high','priority_mid')")
            thresholds = dict(zip(s['key'], s['value'].astype(float)))
            priority_high = int(thresholds.get('priority_high', 100000))
            priority_mid  = int(thresholds.get('priority_mid', 50000))
        except Exception:
            priority_high, priority_mid = 100000, 50000

        return render_template("home.html",
            priority_high=priority_high, priority_mid=priority_mid,
            out=fmt(out), due_amount=fmt(due_amount), due7=fmt(due7), unalloc=unalloc,
            unsettled_on_account=fmt(unsettled_on_account), suspense_amount=fmt(suspense_amount),
            pdc_count=pdc_count, pdc_amount=fmt(pdc_amount),
            today_fu_count=len(today_fu_list),
            missed_count=len(missed_fu_list),
            upcoming_count=len(upcoming_fu_list),
            today_fu=today_fu_list, missed_fu=missed_fu_list, upcoming_fu=upcoming_fu_list,
            acc_c=acc_c, acc_a=fmt(acc_a), sr_c=sr_c, sr_a=fmt(sr_a),
            own_c=own_c, own_a=fmt(own_a),
            unassigned_c=unassigned_c, unassigned_a=fmt(unassigned_a),
            fu_counts=fu_counts, user_fu_list=user_fu_list,
            today_date=date.today().strftime('%d-%b-%Y'),
            top=top.to_dict("records"), last_sync=last_sync,
            active_users=active_users,
            user_ticket_counts=user_ticket_counts,
            role=role, username=un, tally_name=tn,
        )

    except Exception as e:
        import traceback, logging
        err = traceback.format_exc()
        logging.getLogger(__name__).error(f"HOME PAGE ERROR: {e}\n{err}")
        print(f"HOME PAGE ERROR: {e}")
        print(err)
        try:
            s = query_df("SELECT key, value FROM app_settings WHERE key IN ('priority_high','priority_mid')")
            thresholds = dict(zip(s['key'], s['value'].astype(float)))
            priority_high = int(thresholds.get('priority_high', 100000))
            priority_mid  = int(thresholds.get('priority_mid', 50000))
        except Exception:
            priority_high, priority_mid = 100000, 50000

        return render_template("home.html",
            priority_high=priority_high, priority_mid=priority_mid,
            error=str(e) + " | " + err.split("\n")[-2],
            role=role, username=un, tally_name=tn,
            today_fu=[], missed_fu=[], upcoming_fu=[], unalloc="₹0", due_amount="₹0",
            today_fu_count=0, missed_count=0, upcoming_count=0,
            unsettled_on_account="₹0", suspense_amount="₹0",
            pdc_count=0, pdc_amount="₹0",
            top=[], acc_c=0, acc_a="₹0", sr_c=0, sr_a="₹0",
            own_c=0, own_a="₹0", unassigned_c=0, unassigned_a="₹0", out="₹0", due7="₹0",
            fu_counts={"Accounts Team":{"today":0,"d7":0,"d30":0,"overall":0},
                       "Senior Accountant":{"today":0,"d7":0,"d30":0,"overall":0},
                       "Owner":{"today":0,"d7":0,"d30":0,"overall":0}},
            user_fu_list=[],
            active_users=[],
            user_ticket_counts={},
            today_date=date.today().strftime('%d-%b-%Y'),
            last_sync=None)
