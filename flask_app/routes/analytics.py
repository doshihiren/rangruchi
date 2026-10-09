from flask import Blueprint, render_template
from flask_app.routes.auth import login_required
from db import query_df
import pandas as pd

analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/analytics")
@login_required
def analytics():
    # Aging
    bills = query_df("SELECT invoice_date,pending_amount FROM billwise WHERE pending_amount>0")
    aging_data = []
    if not bills.empty:
        bills["dt"] = pd.to_datetime(bills["invoice_date"], errors="coerce")
        bills["days"] = (pd.Timestamp.today()-bills["dt"]).dt.days
        def bkt(d):
            if pd.isna(d): return "Unknown"
            if d<=7: return "0-7d"
            if d<=30: return "8-30d"
            if d<=90: return "31-90d"
            if d<=180: return "91-180d"
            return "180+d"
        bills["bucket"]=bills["days"].apply(bkt)
        aging_data=bills.groupby("bucket")["pending_amount"].agg(["count","sum"]).reset_index().rename(columns={"bucket":"Bucket","count":"Bills","sum":"Amount"}).to_dict("records")

    # Agent perf
    agent_perf = query_df("""SELECT agent_name,COUNT(*) tickets,COALESCE(SUM(pending_amount),0) outstanding
        FROM tickets WHERE agent_name IS NOT NULL GROUP BY agent_name ORDER BY outstanding DESC""").to_dict("records")

    # Agency perf
    agency_perf = query_df("""SELECT agency_name,COUNT(*) tickets,COALESCE(SUM(pending_amount),0) outstanding
        FROM tickets WHERE agency_name IS NOT NULL AND UPPER(agency_name)!='DIRECT'
        GROUP BY agency_name ORDER BY outstanding DESC""").to_dict("records")

    # Top outstanding
    top_out = query_df("SELECT party_name,balance FROM outstanding WHERE balance>0 ORDER BY balance DESC LIMIT 20").to_dict("records")

    # Follow-up trends
    fu_status = query_df("SELECT status,COUNT(*) cnt FROM followups GROUP BY status ORDER BY cnt DESC").to_dict("records")

    return render_template("analytics.html",
        aging_data=aging_data, agent_perf=agent_perf,
        agency_perf=agency_perf, top_out=top_out, fu_status=fu_status)
