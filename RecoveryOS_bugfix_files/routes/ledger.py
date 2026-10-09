from flask import Blueprint, render_template, request, session, abort, make_response
from flask_app.routes.auth import login_required
from db import query_df, execute
import pandas as pd
from datetime import date
import urllib.parse
import re

ledger_bp = Blueprint("ledger", __name__)

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

def get_allowed_parties_df():
    # Everyone with login access can VIEW any party's ledger (read-only access).
    # Assignment restrictions still apply on Tickets/Follow-ups pages, not here.
    base_sql = """SELECT t.party_name, t.ticket_number, t.party_mobile, t.agency_name
                   FROM tickets t"""
    df = query_df(f"{base_sql} ORDER BY t.party_name")
    extra = query_df("""SELECT DISTINCT party_name, NULL AS ticket_number,
                        NULL AS party_mobile, NULL AS agency_name
                        FROM billwise WHERE party_name NOT IN
                        (SELECT party_name FROM tickets) ORDER BY party_name""")
    if not extra.empty:
        df = pd.concat([df, extra], ignore_index=True)
    return df

def get_allowed_parties():
    df = get_allowed_parties_df()
    return df["party_name"].tolist() if not df.empty else []

@ledger_bp.route("/ledger")
@login_required
def ledger():
    search   = request.args.get("q","")
    selected_raw = request.args.get("party","")
    selected = urllib.parse.unquote(selected_raw) if selected_raw else ""

    parties_df = get_allowed_parties_df()
    parties    = parties_df["party_name"].tolist() if not parties_df.empty else []

    if search and not parties_df.empty:
        mask = parties_df.apply(lambda r: any(
            smart_match(r.get(f,""), search)
            for f in ["party_name","ticket_number","party_mobile","agency_name"]
        ), axis=1)
        filtered = parties_df[mask]["party_name"].tolist()
    else:
        filtered = parties

    if selected and selected not in filtered:
        if search and selected in parties:
            filtered = [selected] + filtered
        elif not search:
            filtered = parties

    if not selected and filtered:
        selected = filtered[0]

    role = session.get("role","")
    # All logged-in users may view any party's ledger; 403 only if truly not found
    # Normalize double spaces before 404 check
    if selected:
        sel_norm = " ".join(selected.split())
        parties_norm = {" ".join(p.split()): p for p in parties}
        if sel_norm in parties_norm:
            selected = parties_norm[sel_norm]  # use exact DB name
        elif selected not in parties:
            abort(404)

    data = {
        "selected": selected,
        "bills": [], "balance": 0.0, "unallocated": 0.0,
        "agent": "—", "agency": "—", "agency_mobile": "",
        "seller": "—", "state": "—", "place": "—", "mobile": "",
        "place_of_supply": "—", "gstin": "",
        "followups": [], "oldest": 0, "total_pending": 0.0,
        "pdc_entries": [], "pdc_total": 0.0, "due_amount": 0.0,
    }

    if selected:
        bills = query_df("""
            SELECT * FROM billwise WHERE party_name=%s
            ORDER BY CASE WHEN invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
                          THEN TO_DATE(invoice_date,'DD-Mon-YY') ELSE NULL END ASC NULLS LAST
        """, (selected,))
        outstanding = query_df("SELECT balance FROM outstanding WHERE party_name=%s", (selected,))
        mapping = query_df("SELECT * FROM salesperson_mapping WHERE party_name=%s", (selected,))
        assigned_row = query_df("SELECT assigned_to, assigned_on FROM tickets WHERE party_name=%s LIMIT 1", (selected,))
        assigned_to  = str(assigned_row.iloc[0]["assigned_to"] or "") if not assigned_row.empty else ""
        assigned_on  = str(assigned_row.iloc[0]["assigned_on"] or "") if not assigned_row.empty else ""
        assigned_row = query_df("SELECT assigned_to, assigned_on FROM tickets WHERE party_name=%s LIMIT 1", (selected,))
        assigned_to  = str(assigned_row.iloc[0]["assigned_to"] or "") if not assigned_row.empty else ""
        assigned_on  = str(assigned_row.iloc[0]["assigned_on"] or "") if not assigned_row.empty else ""
        fu = query_df("SELECT * FROM followups WHERE party_name=%s ORDER BY created_at DESC", (selected,))

        # PDC: match on normalized party name so spacing/case diffs still show in ledger
        try:
            pdc = query_df("""
                SELECT voucher_number, cheque_date, amount, narration, voucher_type,
                       voucher_date, instrument_date, instrument_number, bill_refs
                FROM pdc_entries
                WHERE regexp_replace(UPPER(party_name), '\\s+', ' ', 'g')
                    = regexp_replace(UPPER(%s), '\\s+', ' ', 'g')
                ORDER BY COALESCE(instrument_date, cheque_date) ASC
            """, (selected,))
        except Exception:
            pdc = query_df("""
                SELECT voucher_number, cheque_date, amount, narration, voucher_type,
                       NULL AS voucher_date, NULL AS instrument_date,
                       NULL AS instrument_number, NULL AS bill_refs
                FROM pdc_entries
                WHERE regexp_replace(UPPER(party_name), '\\s+', ' ', 'g')
                    = regexp_replace(UPPER(%s), '\\s+', ' ', 'g')
                ORDER BY cheque_date ASC
            """, (selected,))
        pdc_entries = pdc.to_dict("records") if not pdc.empty else []

        # Pull mobile, agency, POS from tally_party_master
        # Normalize multiple spaces so "MARS CLOTHING  BENGALURU" matches "MARS CLOTHING BENGALURU"
        _sel_norm = " ".join(selected.split())
        tpm = query_df(
            "SELECT * FROM tally_party_master WHERE"
            " regexp_replace(party_name, '\\s+', ' ', 'g') = %s",
            (_sel_norm,))
        tm  = tpm.iloc[0].to_dict() if not tpm.empty else {}

        # Ticket row — same source tickets page uses for agency_full / agency_phone
        ticket_row = query_df(
            "SELECT agency_name, agency_mobile, credit_days FROM tickets WHERE party_name=%s LIMIT 1",
            (selected,),
        )
        tix = ticket_row.iloc[0].to_dict() if not ticket_row.empty else {}

        m = mapping.iloc[0].to_dict() if not mapping.empty else {}
        # Prefer ticket credit_days (kept current by sync), then salesperson_mapping
        try:
            credit_period = int(tix.get("credit_days") or m.get("credit_period_days") or 30)
        except (TypeError, ValueError):
            credit_period = 30

        if not bills.empty:
            bills["dt"] = pd.to_datetime(bills["invoice_date"], errors="coerce")
            bills["aging_days"] = (pd.Timestamp.today() - bills["dt"]).dt.days.fillna(0).astype(int)
            def bkt(d):
                if d <= 7:  return "0-7d"
                if d <= 30: return "8-30d"
                if d <= 90: return "31-90d"
                return "90+d"
            bills["aging"] = bills["aging_days"].apply(bkt)
            bills["due_dt"] = bills["dt"] + pd.to_timedelta(credit_period, unit="D")
            bills["due_date_str"] = bills["due_dt"].dt.strftime("%d-%b-%y")
            today_ts = pd.Timestamp.today().normalize()
            bills["due_in_days"] = (bills["due_dt"] - today_ts).dt.days.fillna(0).astype(int)

        # Agency name/mobile: same resolution order as /tickets page
        agency_nm = (
            (tm.get("agency_name") or "").strip()
            or (tix.get("agency_name") or "").strip()
            or (m.get("agency_name") or "").strip()
        )
        agency_mobile = ""
        if agency_nm:
            tam = query_df(
                "SELECT mobile FROM tally_agency_master WHERE "
                "regexp_replace(UPPER(agency_name),'\\s+',' ','g')=regexp_replace(UPPER(%s),'\\s+',' ','g')",
                (agency_nm,))
            if not tam.empty and tam.iloc[0]["mobile"]:
                mob = str(tam.iloc[0]["mobile"] or "")
            else:
                # Fallback: tickets.agency_mobile, then agency ledger mobile in salesperson_mapping
                mob = str(tix.get("agency_mobile") or "")
                if not mob or len("".join(c for c in mob if c.isdigit())) < 10:
                    am = query_df(
                        "SELECT party_mobile FROM salesperson_mapping WHERE UPPER(party_name)=UPPER(%s)",
                        (agency_nm,),
                    )
                    mob = str(am.iloc[0]["party_mobile"] or "") if not am.empty else mob
            digits = "".join(c for c in mob.split(",")[0].split("/")[0] if c.isdigit())
            if len(digits) >= 10:
                agency_mobile = "+91 " + digits[-10:-5] + " " + digits[-5:]

        ledger_balance = float(outstanding.iloc[0]["balance"]) if not outstanding.empty else None
        billwise_sum   = float(bills["pending_amount"].sum()) if not bills.empty else 0
        # Only compute unallocated when we actually have an outstanding ledger balance to compare against.
        # If outstanding row is missing, we cannot reliably detect an advance - assume 0 (no false positive).
        if ledger_balance is None:
            unallocated = 0
        else:
            unallocated = max(0, billwise_sum - abs(ledger_balance))

        # Resolve fields: tally_party_master > salesperson_mapping
        party_mobile_raw = (tm.get("mobile") or "").strip() or (m.get("party_mobile") or "").strip()
        party_state      = (tm.get("state") or "").strip() or (m.get("party_state") or "") or "—"
        party_place      = (tm.get("place_udf") or "").strip() or (m.get("party_place") or "") or "—"
        party_pos        = (tm.get("place_of_supply") or "").strip() or party_state

        # All pending bills
        all_pending_df = bills[bills["pending_amount"] > 0] if not bills.empty else pd.DataFrame()
        # On-account bills (unsettled receipts)
        onacct_mask = all_pending_df["invoice_no"].str.contains("on account", case=False, na=False) if not all_pending_df.empty else pd.Series([], dtype=bool)
        onacct_df2  = all_pending_df[onacct_mask] if not all_pending_df.empty else pd.DataFrame()
        # Due bills: past credit period, not on-account
        if not all_pending_df.empty and "due_in_days" in all_pending_df.columns:
            due_bills_df = all_pending_df[
                (~onacct_mask) & (all_pending_df["due_in_days"] <= 0)
            ]
        else:
            due_bills_df = all_pending_df[~onacct_mask] if not all_pending_df.empty else pd.DataFrame()
        bills_due_total  = float(due_bills_df["pending_amount"].sum()) if not due_bills_df.empty else 0.0
        pdc_amount_total = sum(float(p.get("amount", 0)) for p in pdc_entries)
        # Net due = overdue bills - PDC - unallocated
        due_amount       = max(0.0, bills_due_total - pdc_amount_total - unallocated)

        data.update({
            "bills":            due_bills_df.to_dict("records") if not due_bills_df.empty else [],
            "balance":          abs(ledger_balance) if ledger_balance is not None else 0.0,
            "unallocated":      unallocated,
            "agent":            m.get("agent_name","—"),
            "agency":           agency_nm or "—",
            "agency_mobile":    agency_mobile,
            "seller":           m.get("seller_name","—"),
            "state":            party_state,
            "place":            party_place,
            "place_of_supply":  party_pos,
            "mobile":           party_mobile_raw,
            "gstin":            (tm.get("gstin") or "").strip(),
            "assigned_to":      assigned_to,
            "assigned_on":      assigned_on,
            "assigned_to":      assigned_to,
            "assigned_on":      assigned_on,
            "followups":        fu.to_dict("records") if not fu.empty else [],
            "oldest":           int(bills["aging_days"].max()) if not bills.empty else 0,
            "total_pending":    due_amount,
            "pdc_entries":      pdc_entries,
            "pdc_total":        pdc_amount_total,
            "due_amount":       due_amount,
            "bills_due_total":  bills_due_total,
        })

    return render_template("ledger.html",
        parties=filtered, search=search,
        total_parties=len(parties), **data)


@ledger_bp.route("/pdc")
@login_required
def pdc_list():
    from datetime import timedelta
    role = session.get("role","")

    # Filters
    q         = request.args.get("q","").strip()
    from_date = request.args.get("from_date","").strip()
    to_date   = request.args.get("to_date","").strip()
    overdue   = request.args.get("overdue","")
    days      = request.args.get("days","")

    # Quick filters
    today = date.today()
    if overdue == "1":
        from_date = "2000-01-01"
        to_date   = str(today - timedelta(days=1))
    elif days:
        from_date = str(today)
        to_date   = str(today + timedelta(days=int(days)))

    # Build WHERE clause — prefer instrument (cheque) date when present
    where = []
    params = []
    if from_date:
        where.append("COALESCE(p.instrument_date, p.cheque_date) >= %s")
        params.append(from_date)
    if to_date:
        where.append("COALESCE(p.instrument_date, p.cheque_date) <= %s")
        params.append(to_date)
    if q:
        where.append(
            "(p.party_name ILIKE %s OR t.agency_name ILIKE %s"
            " OR COALESCE(p.bill_refs,'') ILIKE %s"
            " OR COALESCE(p.instrument_number,'') ILIKE %s)"
        )
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    try:
        pdc = query_df(f"""
            SELECT p.party_name, p.voucher_number,
                   COALESCE(p.instrument_date, p.cheque_date)::text AS cheque_date,
                   p.voucher_date::text AS voucher_date,
                   p.instrument_date::text AS instrument_date,
                   p.instrument_number, p.bill_refs,
                   p.amount, p.narration, p.voucher_type,
                   COALESCE(NULLIF(tpm.agency_name,''), t.agency_name) AS agency_name,
                   t.agent_name,
                   COALESCE(NULLIF(tpm.state,''), t.party_state) AS party_state,
                   COALESCE(NULLIF(tpm.mobile,''), t.party_mobile) AS party_mobile
            FROM pdc_entries p
            LEFT JOIN tickets t
              ON regexp_replace(upper(t.party_name),'\\s+',' ','g')
               = regexp_replace(upper(p.party_name),'\\s+',' ','g')
            LEFT JOIN tally_party_master tpm ON tpm.party_name_norm = t.party_name_norm
            {where_sql}
            ORDER BY COALESCE(p.instrument_date, p.cheque_date) ASC
        """, params if params else None)
    except Exception:
        # Columns not yet created — fall back until next sync_pdc() runs
        where2, params2 = [], []
        if from_date:
            where2.append("p.cheque_date >= %s"); params2.append(from_date)
        if to_date:
            where2.append("p.cheque_date <= %s"); params2.append(to_date)
        if q:
            where2.append("(p.party_name ILIKE %s OR t.agency_name ILIKE %s)")
            params2.extend([f"%{q}%", f"%{q}%"])
        where_sql2 = ("WHERE " + " AND ".join(where2)) if where2 else ""
        pdc = query_df(f"""
            SELECT p.party_name, p.voucher_number, p.cheque_date::text AS cheque_date,
                   NULL AS voucher_date, NULL AS instrument_date,
                   NULL AS instrument_number, NULL AS bill_refs,
                   p.amount, p.narration, p.voucher_type,
                   COALESCE(NULLIF(tpm.agency_name,''), t.agency_name) AS agency_name,
                   t.agent_name,
                   COALESCE(NULLIF(tpm.state,''), t.party_state) AS party_state,
                   COALESCE(NULLIF(tpm.mobile,''), t.party_mobile) AS party_mobile
            FROM pdc_entries p
            LEFT JOIN tickets t
              ON regexp_replace(upper(t.party_name),'\\s+',' ','g')
               = regexp_replace(upper(p.party_name),'\\s+',' ','g')
            LEFT JOIN tally_party_master tpm ON tpm.party_name_norm = t.party_name_norm
            {where_sql2}
            ORDER BY p.cheque_date ASC
        """, params2 if params2 else None)

    total_amount = float(pdc["amount"].sum()) if not pdc.empty else 0
    total_count  = len(pdc)

    summary = []
    if not pdc.empty:
        grp = pdc.groupby("party_name").agg(
            cheques=("amount","count"),
            total=("amount","sum")
        ).reset_index()
        summary = grp.sort_values("total", ascending=False).to_dict("records")

    records = pdc.to_dict("records") if not pdc.empty else []

    return render_template("pdc.html",
        records=records,
        summary=summary,
        total_amount=total_amount,
        total_count=total_count,
        today_date=today.strftime('%d-%b-%Y'),
        role=role,
    )
