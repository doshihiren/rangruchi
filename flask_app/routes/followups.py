from flask import Blueprint, render_template, session, request, redirect, url_for, flash
from flask_app.routes.auth import login_required
from db import query_df, execute, fetchone
from datetime import date, timedelta
import re

followups_bp = Blueprint("followups", __name__)

# ── Helpers ──────────────────────────────────────────────────────────────────

def smart_match(text, q):
    if not text or not q: return False
    t = str(text).upper().strip()
    q = q.upper().strip()
    if q in t: return True
    if q.replace(" ","") in t.replace(" ",""): return True
    words = re.split(r"[\s\-&/]+", t)
    initials = "".join(w[0] for w in words if w)
    if q == initials or initials.startswith(q): return True
    return False

def get_fu_filter():
    """Filter followups by ticket assigned_to = current user (everyone incl Owner)."""
    un = session.get("username","")
    return (
        "WHERE EXISTS (SELECT 1 FROM tickets t2 WHERE t2.party_name=f.party_name AND t2.assigned_to=%s)",
        (un,)
    )

def get_ticket_filter():
    role = session.get("role","")
    un   = session.get("username","")
    if role == "Owner": return "", ()
    return "WHERE assigned_to=%s", (un,)

# ── BASE SQL ──────────────────────────────────────────────────────────────────

BASE_SQL = r"""SELECT f.id, f.ticket_id, f.party_name, f.bill_no, f.status,
    f.priority, f.last_call_date, f.next_followup_date, f.promise_amount,
    f.assigned_to, f.assigned_role, f.notes, f.created_at, f.created_by,
    t.pending_amount AS outstanding,
    COALESCE(NULLIF(tpm.mobile,''), t.party_mobile) AS party_mobile,
    t.agent_name,
    COALESCE(NULLIF(tpm.agency_name,''), t.agency_name) AS agency_name,
    t.seller_name,
    COALESCE(NULLIF(tpm.state,''), t.party_state) AS party_state,
    COALESCE(NULLIF(tpm.place_udf,''), t.party_place) AS party_place,
    COALESCE(NULLIF(tpm.place_of_supply,''), t.party_state) AS place_of_supply,
    t.ticket_number,
    t.assigned_to AS ticket_assigned_to,
    t.net_due
    FROM followups f
    LEFT JOIN tickets t ON t.party_name = f.party_name
    LEFT JOIN tally_party_master tpm
        ON tpm.party_name_norm = regexp_replace(UPPER(f.party_name),'\s+',' ','g')
    WHERE (f.archived IS NULL OR f.archived = FALSE)
    AND COALESCE(t.net_due, 0) > 0"""

LATEST = "AND f.id = (SELECT MAX(f2.id) FROM followups f2 WHERE f2.party_name=f.party_name)"

def build_where(fh, extra=""):
    """Build WHERE clause combining base filter with extra conditions."""
    if fh:
        return f"AND EXISTS (SELECT 1 FROM tickets t2 WHERE t2.party_name=f.party_name AND t2.assigned_to=%s){extra}"
    return extra

def run_query(sql, params):
    return query_df(sql, params if params else None)

def add_history(rows):
    result = []
    for row in rows:
        h = query_df(
            "SELECT last_call_date, next_followup_date, status, notes, assigned_to, created_by "
            "FROM followups WHERE party_name=%s ORDER BY created_at ASC",
            (row["party_name"],)
        )
        row["history"] = h.to_dict("records") if not h.empty else []
        mob = str(row.get("party_mobile") or "")
        row["mobile_display"] = mob[-10:] if len(mob) >= 10 else ""
        result.append(row)
    return result

# ── Main followups route ──────────────────────────────────────────────────────

@followups_bp.route("/followups")
@login_required
def followups():
    fh, fp  = get_fu_filter()
    wh, wp  = get_ticket_filter()
    un      = session.get("username","")
    role    = session.get("role","")
    tab     = request.args.get("tab","today")
    search  = request.args.get("q","").strip()
    aging   = request.args.get("aging","").strip()
    if aging in ("120 ","120"): aging = "120+"
    period  = request.args.get("period","").strip()

    # Build per-tab WHERE clauses (all append to BASE_SQL which already has WHERE)
    user_cond = "AND EXISTS (SELECT 1 FROM tickets t2 WHERE t2.party_name=f.party_name AND t2.assigned_to=%s)"
    status_ex = "AND f.status NOT IN ('Paid','Closed','Dispute')"

    w_today    = f"{user_cond} {status_ex} AND f.next_followup_date=CURRENT_DATE {LATEST}"
    w_overdue  = f"{user_cond} {status_ex} AND f.next_followup_date<CURRENT_DATE {LATEST}"
    w_upcoming = f"{user_cond} {status_ex} AND f.next_followup_date>CURRENT_DATE AND f.next_followup_date<=CURRENT_DATE+7 {LATEST}"
    w_all      = f"{user_cond}"

    today_df    = run_query(f"{BASE_SQL} {w_today}    ORDER BY f.priority DESC",          fp)
    overdue_df  = run_query(f"{BASE_SQL} {w_overdue}  ORDER BY f.next_followup_date",     fp)
    upcoming_df = run_query(f"{BASE_SQL} {w_upcoming} ORDER BY f.next_followup_date",     fp)
    all_df      = run_query(f"{BASE_SQL} {w_all}      ORDER BY f.next_followup_date DESC", fp)

    # No Call Yet
    try:
        if role == "Owner":
            nc_df = query_df("""
                SELECT t.party_name, t.ticket_number, t.net_due, t.assigned_to,
                       t.party_mobile, t.agency_name, t.party_state
                FROM tickets t WHERE t.net_due > 0
                AND t.assigned_to IS NOT NULL AND t.assigned_to != ''
                AND NOT EXISTS (SELECT 1 FROM followups f WHERE f.party_name=t.party_name AND (f.archived IS NULL OR f.archived=FALSE))
                ORDER BY t.net_due DESC""")
        else:
            nc_df = query_df("""
                SELECT t.party_name, t.ticket_number, t.net_due, t.assigned_to,
                       t.party_mobile, t.agency_name, t.party_state
                FROM tickets t WHERE t.net_due > 0 AND t.assigned_to=%s
                AND NOT EXISTS (SELECT 1 FROM followups f WHERE f.party_name=t.party_name AND (f.archived IS NULL OR f.archived=FALSE))
                ORDER BY t.net_due DESC""", (un,))
        no_call_list = nc_df.to_dict("records") if not nc_df.empty else []
    except Exception as ex:
        print(f"no_call_yet error: {ex}")
        no_call_list = []

    # Tickets dropdown for add-followup form (only parties still having net due)
    if wh:
        tickets = run_query(
            f"SELECT party_name, bill_no, pending_amount, id FROM tickets {wh} AND COALESCE(net_due,0) > 0 ORDER BY party_name",
            wp if wp else None
        )
    else:
        tickets = run_query(
            "SELECT party_name, bill_no, pending_amount, id FROM tickets WHERE COALESCE(net_due,0) > 0 ORDER BY party_name",
            None
        )

    today_fu    = add_history(today_df.to_dict("records")    if not today_df.empty    else [])
    overdue_fu  = add_history(overdue_df.to_dict("records")  if not overdue_df.empty  else [])
    upcoming_fu = add_history(upcoming_df.to_dict("records") if not upcoming_df.empty else [])
    all_fu      = add_history(all_df.to_dict("records")      if not all_df.empty      else [])

    # Smart search filter
    if search:
        def _match(f):
            return any(smart_match(f.get(k,""), search) for k in
                ("party_name","ticket_number","agency_name","agent_name",
                 "party_mobile","party_state","party_place","place_of_supply"))
        today_fu    = [f for f in today_fu    if _match(f)]
        overdue_fu  = [f for f in overdue_fu  if _match(f)]
        upcoming_fu = [f for f in upcoming_fu if _match(f)]
        all_fu      = [f for f in all_fu      if _match(f)]
        no_call_list= [f for f in no_call_list if smart_match(f.get("party_name",""), search)]

    # Aging bucket filter
    if aging in ("0-60","61-120","120+"):
        try:
            ages = query_df("""
                SELECT party_name, MAX(CURRENT_DATE - TO_DATE(invoice_date,'DD-Mon-YY')) AS max_age
                FROM billwise WHERE pending_amount > 0
                AND invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
                GROUP BY party_name""")
            if not ages.empty:
                if aging == "0-60":   aged = set(ages[ages["max_age"] < 60]["party_name"])
                elif aging == "61-120": aged = set(ages[(ages["max_age"]>=60)&(ages["max_age"]<120)]["party_name"])
                else:                  aged = set(ages[ages["max_age"]>=120]["party_name"])
                today_fu    = [f for f in today_fu    if f.get("party_name") in aged]
                overdue_fu  = [f for f in overdue_fu  if f.get("party_name") in aged]
                upcoming_fu = [f for f in upcoming_fu if f.get("party_name") in aged]
                all_fu      = [f for f in all_fu      if f.get("party_name") in aged]
        except Exception: pass

    # Period filter (today / d7 / d30) on last_call_date
    if period in ("today","d7","d30"):
        today_d = date.today()
        cutoff  = today_d if period=="today" else today_d - timedelta(days=7 if period=="d7" else 30)
        def _in_period(f):
            lcd = f.get("last_call_date")
            if not lcd: return False
            try:
                lcd_d = lcd if hasattr(lcd,"year") else date.fromisoformat(str(lcd)[:10])
                return lcd_d == today_d if period=="today" else lcd_d >= cutoff
            except: return False
        today_fu    = [f for f in today_fu    if _in_period(f)]
        overdue_fu  = [f for f in overdue_fu  if _in_period(f)]
        upcoming_fu = [f for f in upcoming_fu if _in_period(f)]
        all_fu      = [f for f in all_fu      if _in_period(f)]

    return render_template("followups.html",
        today_fu    = today_fu,
        overdue     = overdue_fu,
        upcoming    = upcoming_fu,
        all_fu      = all_fu,
        no_call_yet = no_call_list,
        tickets     = tickets.to_dict("records") if not tickets.empty else [],
        tab         = tab,
        search      = search,
        aging       = aging,
        period      = period,
        role        = role,
        counts      = {
            "today":   len(today_fu),
            "overdue": len(overdue_fu),
            "upcoming":len(upcoming_fu),
            "all":     len(all_fu),
            "nocall":  len(no_call_list),
        }
    )

# ── Add followup ──────────────────────────────────────────────────────────────

@followups_bp.route("/followups/add", methods=["POST"])
@login_required
def add_followup():
    un    = session.get("username")
    role  = session.get("role")
    f     = request.form
    party = f.get("party_name","").strip()
    if not party:
        flash("Party name is required.", "error")
        return redirect(request.referrer or url_for("followups.followups"))

    notes_val = (f.get("notes","") or "").strip()
    if not notes_val:
        flash("Remarks/Notes is required.", "error")
        return redirect(request.referrer or url_for("followups.followups"))

    ticket_id = f.get("ticket_id") or None
    if not ticket_id:
        t = fetchone("SELECT id FROM tickets WHERE party_name=%s LIMIT 1", (party,))
        if t: ticket_id = t["id"]
    try:
        ticket_id = int(ticket_id) if ticket_id else None
    except: ticket_id = None

    # assigned_to = ticket's assigned user, fallback to current user
    ta = fetchone("SELECT assigned_to FROM tickets WHERE party_name=%s LIMIT 1", (party,))
    fu_assigned_to = (ta["assigned_to"] if ta and ta.get("assigned_to") else un)

    today_str = str(date.today())
    next_date = (f.get("next_followup_date") or "").strip() or today_str

    try:
        execute("""INSERT INTO followups
            (ticket_id, party_name, bill_no, status, priority,
             last_call_date, next_followup_date, promise_amount,
             assigned_to, assigned_role, notes, created_by, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
            (ticket_id, party, f.get("bill_no","") or "",
             f.get("status","Pending"), f.get("priority","Medium"),
             today_str, next_date, 0.0,
             fu_assigned_to, role, notes_val, un))
        flash(f"Follow-up saved for {party}!", "success")
    except Exception as _e:
        import traceback; traceback.print_exc()
        flash(f"Error saving follow-up: {_e}", "error")
        return redirect(request.referrer or url_for("followups.followups"))

    ref = request.referrer or ""
    if "ledger" in ref:
        return redirect(ref)
    return redirect(url_for("followups.followups"))

# ── Update followup ───────────────────────────────────────────────────────────

@followups_bp.route("/followups/update", methods=["POST"])
@login_required
def update_followup():
    un   = session.get("username")
    role = session.get("role")

    _id_raw = (request.form.get("id") or "").strip()
    if not _id_raw or _id_raw == "undefined":
        flash("Invalid follow-up ID.", "error")
        return redirect(request.referrer or url_for("followups.followups"))
    fu_id = int(_id_raw)

    status = request.form.get("status","Pending")
    next_d = (request.form.get("next_date") or request.form.get("next_followup_date") or "").strip()
    today  = str(date.today())
    if not next_d or len(next_d) < 8:
        next_d = today

    notes = (request.form.get("notes") or "").strip()
    if not notes:
        flash("Remarks/Notes is required.", "error")
        tab   = request.form.get("tab","today")
        aging = request.form.get("aging","")
        return redirect(url_for("followups.followups", tab=tab, aging=aging))

    old = fetchone("SELECT party_name, bill_no, ticket_id FROM followups WHERE id=%s", (fu_id,))
    if not old:
        flash("Follow-up not found.", "error")
        return redirect(url_for("followups.followups"))

    # assigned_to = ticket's assigned user
    ta = fetchone("SELECT assigned_to FROM tickets WHERE party_name=%s LIMIT 1", (old["party_name"],))
    fu_assigned_to = (ta["assigned_to"] if ta and ta.get("assigned_to") else un)

    execute("""INSERT INTO followups
        (ticket_id, party_name, bill_no, status, priority,
         last_call_date, next_followup_date, promise_amount,
         assigned_to, assigned_role, notes, created_by, created_at, updated_at)
        VALUES (%s,%s,%s,%s,
            COALESCE((SELECT priority FROM followups WHERE id=%s),'Medium'),
            %s,%s,0.0,%s,%s,%s,%s,NOW(),NOW())""",
        (old["ticket_id"], old["party_name"], old["bill_no"], status,
         fu_id, today, next_d, fu_assigned_to, role, notes, un))

    flash("Follow-up updated.", "success")
    tab   = request.form.get("tab","today")
    aging = request.form.get("aging","")
    return redirect(url_for("followups.followups", tab=tab, aging=aging))
