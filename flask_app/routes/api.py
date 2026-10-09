from flask import Blueprint, jsonify, session
from flask_app.routes.auth import login_required
from db import query_df

api_bp = Blueprint("api", __name__, url_prefix="/api")

@api_bp.route("/agent-chart")
@login_required
def agent_chart():
    df = query_df("SELECT agent_name,COALESCE(SUM(pending_amount),0) amt FROM tickets WHERE agent_name IS NOT NULL GROUP BY agent_name ORDER BY amt DESC LIMIT 8")
    return jsonify({"labels": df["agent_name"].tolist(), "data": df["amt"].tolist()})

@api_bp.route("/aging-chart")
@login_required
def aging_chart():
    import pandas as pd
    df = query_df("SELECT invoice_date,pending_amount FROM billwise WHERE pending_amount>0")
    if df.empty: return jsonify({"labels":[],"data":[]})
    df["dt"]=pd.to_datetime(df["invoice_date"],errors="coerce")
    df["days"]=(pd.Timestamp.today()-df["dt"]).dt.days
    def bkt(d):
        if pd.isna(d): return "Unknown"
        if d<=7: return "0-7d"
        if d<=30: return "8-30d"
        if d<=90: return "31-90d"
        return "90+d"
    df["b"]=df["days"].apply(bkt)
    g=df.groupby("b")["pending_amount"].sum()
    order=["0-7d","8-30d","31-90d","90+d","Unknown"]
    g=g.reindex([x for x in order if x in g.index])
    return jsonify({"labels":g.index.tolist(),"data":g.values.tolist()})

@api_bp.route("/status-chart")
@login_required
def status_chart():
    role=session.get("role",""); un=session.get("username","")
    if role in ("Owner","Admin"):
        df=query_df("SELECT status,COUNT(*) cnt FROM followups GROUP BY status")
    else:
        df=query_df("SELECT status,COUNT(*) cnt FROM followups WHERE assigned_to=%s OR created_by=%s GROUP BY status",(un,un))
    return jsonify({"labels":df["status"].tolist(),"data":df["cnt"].tolist()})

@api_bp.route("/agency-chart")
@login_required
def agency_chart():
    df = query_df("""SELECT agency_name, COALESCE(SUM(pending_amount),0) amt
        FROM tickets WHERE agency_name IS NOT NULL AND UPPER(agency_name)!='DIRECT'
        GROUP BY agency_name ORDER BY amt DESC LIMIT 8""")
    return jsonify({"labels": df["agency_name"].tolist(), "data": df["amt"].tolist()})


@api_bp.route("/search")
@login_required
def search_parties():
    from flask import request as req
    q = req.args.get("q","").strip().upper()
    if len(q) < 2:
        return jsonify([])

    import re
    df = query_df("""SELECT t.party_name, t.pending_amount, COALESCE(NULLIF(tpm.mobile,''),t.party_mobile) AS party_mobile, t.agent_name, COALESCE(NULLIF(tpm.agency_name,''),t.agency_name) AS agency_name FROM tickets t LEFT JOIN tally_party_master tpm ON tpm.party_name_norm=t.party_name_norm WHERE t.pending_amount > 0 ORDER BY t.pending_amount DESC""")
    if df.empty:
        return jsonify([])

    def smart_match(name):
        n = str(name).upper()
        # Direct contains
        if q in n: return True
        # No spaces
        if q.replace(" ","") in n.replace(" ",""): return True
        # Initials
        words = re.split(r"[\s\-&/]+", n)
        initials = "".join(w[0] for w in words if w)
        if initials.startswith(q): return True
        return False

    matched = df[df["party_name"].apply(smart_match)].head(8)
    results = []
    for _, row in matched.iterrows():
        results.append({
            "name": row["party_name"],
            "amount": f"₹{float(row.get('pending_amount',0)):,.0f}",
            "agent": str(row.get("agent_name","") or ""),
        })
    return jsonify(results)
