from flask import Blueprint, render_template, request, session
from flask_app.routes.auth import login_required
from db import query_df

invoices_bp = Blueprint("invoices", __name__)

def get_filter():
    role=session.get("role",""); tn=session.get("tally_name","")
    if role in ("Owner","Admin"): return "",()
    if role=="Agent":  return "AND UPPER(sm.agent_name)=UPPER(%s)",(tn,)
    if role=="Agency": return "AND UPPER(sm.agency_name)=UPPER(%s)",(tn,)
    if role=="Seller": return "AND UPPER(sm.seller_name)=UPPER(%s)",(tn,)
    return "AND 1=0",()

@invoices_bp.route("/invoices")
@login_required
def invoices():
    wh,wp  = get_filter()
    aging  = request.args.get("aging","")   # 0-60, 61-120, 120+
    search = request.args.get("q","").strip()
    state  = request.args.get("state","All")

    # Build aging filter
    if aging == "0-60":
        age_filter = "AND (CURRENT_DATE - TO_DATE(b.invoice_date,'DD-Mon-YY')) >= 0 AND (CURRENT_DATE - TO_DATE(b.invoice_date,'DD-Mon-YY')) < 60"
        age_label  = "👩‍💼 Accounts Team — 0 to 60 Days"
        age_color  = "#185fa5"
    elif aging == "61-120":
        age_filter = "AND (CURRENT_DATE - TO_DATE(b.invoice_date,'DD-Mon-YY')) >= 60 AND (CURRENT_DATE - TO_DATE(b.invoice_date,'DD-Mon-YY')) < 120"
        age_label  = "🧑‍💼 Senior Accountant — 61 to 120 Days"
        age_color  = "#854f0b"
    elif aging in ("120+", "120 ", "120"):
        age_filter = "AND (CURRENT_DATE - TO_DATE(b.invoice_date,'DD-Mon-YY')) >= 120"
        age_label  = "👑 Owner — 120+ Days"
        age_color  = "#a32d2d"
    else:
        age_filter = ""
        age_label  = "All Invoices"
        age_color  = "#534ab7"

    params = wp if wp else ()

    df = query_df(f"""
        SELECT
            b.party_name,
            b.invoice_date,
            b.invoice_no,
            b.pending_amount,
            (CURRENT_DATE - TO_DATE(b.invoice_date,'DD-Mon-YY')) AS days_overdue,
            sm.agent_name,
            sm.agency_name,
            sm.party_state,
            sm.party_mobile
        FROM billwise b
        LEFT JOIN salesperson_mapping sm ON sm.party_name = b.party_name
        WHERE b.pending_amount > 0
        AND b.invoice_date ~ '^[0-9]{{2}}-[A-Za-z]{{3}}-[0-9]{{2}}$'
        AND EXISTS(SELECT 1 FROM tickets t WHERE t.party_name=b.party_name)
        {age_filter}
        {wh}
        ORDER BY days_overdue DESC, b.pending_amount DESC
    """, params if params else None)

    # Apply search
    if search and not df.empty:
        df = df[df["party_name"].str.contains(search, case=False, na=False)]

    # Apply state filter
    states = sorted(df["party_state"].dropna().unique().tolist()) if not df.empty else []
    if state != "All" and not df.empty:
        df = df[df["party_state"]==state]

    total    = float(df["pending_amount"].sum()) if not df.empty else 0
    invoices = df.to_dict("records") if not df.empty else []

    # KPI
    parties = len(df["party_name"].unique()) if not df.empty else 0

    return render_template("invoices.html",
        invoices=invoices, total=total,
        parties=parties, aging=aging,
        age_label=age_label, age_color=age_color,
        states=states, search=search, state=state,
        role=session.get("role","")
    )
