from flask import Blueprint, request, abort, make_response
import urllib.parse, pandas as pd, base64, os
from datetime import date
from flask_app.routes.auth import login_required
from db import query_df

ledger_pdf_bp = Blueprint("ledger_pdf", __name__)

def _load_qr():
    paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "RR-QR.png"),
        os.path.join(os.path.dirname(__file__), "..", "static", "RR-QR.png"),
        r"D:\Followup\Project\RR-QR.png",
    ]
    for p in paths:
        p = os.path.normpath(p)
        if os.path.exists(p):
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode()
    return ""

@ledger_pdf_bp.route("/ledger/pdf")
@login_required
def ledger_pdf():
    selected = urllib.parse.unquote(request.args.get("party", ""))
    if not selected:
        abort(404)

    bills       = query_df("""
        SELECT * FROM billwise WHERE party_name=%s
        ORDER BY CASE WHEN invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
                      THEN TO_DATE(invoice_date,'DD-Mon-YY') ELSE NULL END ASC NULLS LAST
    """, (selected,))
    outstanding = query_df("SELECT balance FROM outstanding WHERE party_name=%s", (selected,))
    mapping     = query_df("SELECT * FROM salesperson_mapping WHERE party_name=%s", (selected,))
    ticket_row  = query_df(
        "SELECT agency_name, agency_mobile, credit_days, party_mobile FROM tickets WHERE party_name=%s LIMIT 1",
        (selected,),
    )
    tix = ticket_row.iloc[0].to_dict() if not ticket_row.empty else {}

    m = mapping.iloc[0].to_dict() if not mapping.empty else {}
    try:
        credit_period = int(tix.get("credit_days") or m.get("credit_period_days") or 30)
    except (TypeError, ValueError):
        credit_period = 30
    bal_val = float(outstanding.iloc[0]["balance"]) if not outstanding.empty else None

    raw_mob = str(m.get("party_mobile") or tix.get("party_mobile") or "")
    digits = "".join(c for c in raw_mob if c.isdigit())
    party_mobile = ("+91 " + digits[-10:-5] + " " + digits[-5:]) if len(digits) >= 10 else ""

    try:
        _sn = " ".join(selected.upper().split())
        _tp = query_df("SELECT * FROM tally_party_master WHERE party_name_norm=%s", (_sn,))
        tm  = _tp.iloc[0].to_dict() if not _tp.empty else {}
    except Exception:
        tm = {}

    # Same agency resolution as /tickets page
    pdf_agency = (
        (tm.get("agency_name") or "").strip()
        or (tix.get("agency_name") or "").strip()
        or (m.get("agency_name") or "").strip()
        or "—"
    )
    pdf_state = (tm.get("state") or "").strip() or m.get("party_state", "—")
    pdf_mobile_raw = (tm.get("mobile") or "").strip() or party_mobile

    agency_mob_pdf = ""
    try:
        if pdf_agency and pdf_agency != "—":
            _an = " ".join(pdf_agency.upper().split())
            _tam = query_df(
                r"SELECT mobile FROM tally_agency_master WHERE regexp_replace(UPPER(agency_name),'\s+',' ','g')=%s",
                (_an,),
            )
            _mob = ""
            if not _tam.empty:
                _mob = str(_tam.iloc[0]["mobile"] or "")
            if not _mob:
                _mob = str(tix.get("agency_mobile") or "")
            if not _mob:
                _am = query_df(
                    "SELECT party_mobile FROM salesperson_mapping WHERE UPPER(party_name)=UPPER(%s)",
                    (pdf_agency,),
                )
                _mob = str(_am.iloc[0]["party_mobile"] or "") if not _am.empty else ""
            _mob = _mob.split(",")[0].split("/")[0].strip()
            _d = "".join(c for c in _mob if c.isdigit())
            if len(_d) >= 10:
                agency_mob_pdf = _d[-10:]
    except Exception:
        pass

    try:
        s    = query_df("SELECT key, value FROM app_settings WHERE key LIKE 'bank_%' OR key = 'upi_id'")
        bank = dict(zip(s["key"], s["value"])) if not s.empty else {}
    except Exception:
        bank = {}

    bank_name   = bank.get("bank_name",   "ICICI BANK")
    bank_acc    = bank.get("bank_acc",    "091751000017")
    bank_ifsc   = bank.get("bank_ifsc",   "ICIC0000917")
    bank_branch = bank.get("bank_branch", "New Cloth Market, Ahmedabad - 380002")
    bank_holder = bank.get("bank_holder", "RANGRUCHI FASHION PRIVATE LIMITED")
    upi_id      = bank.get("upi_id",      "RANGRUCHIFASHIONPVTLTD@icici")

    try:
        pdc_df = query_df("""
            SELECT voucher_number,
                   COALESCE(instrument_date, cheque_date)::text AS cheque_date,
                   instrument_date::text AS instrument_date,
                   instrument_number, bill_refs,
                   amount, narration
            FROM pdc_entries
            WHERE regexp_replace(UPPER(party_name), '\\s+', ' ', 'g')
                = regexp_replace(UPPER(%s), '\\s+', ' ', 'g')
            ORDER BY COALESCE(instrument_date, cheque_date)
        """, (selected,))
        pdc_total = float(pdc_df["amount"].sum()) if not pdc_df.empty else 0.0
    except Exception:
        pdc_df    = pd.DataFrame()
        pdc_total = 0.0

    due_rows_html = ""
    pdc_rows_html = ""
    total_due     = 0.0
    unalloc_pdf   = 0.0

    if not bills.empty:
        bills["dt"]           = pd.to_datetime(bills["invoice_date"], format="%d-%b-%y", errors="coerce")
        bills["aging_days"]   = (pd.Timestamp.today() - bills["dt"]).dt.days.fillna(0).astype(int)
        bills["due_dt"]       = bills["dt"] + pd.to_timedelta(credit_period, unit="D")
        bills["due_date_str"] = bills["due_dt"].dt.strftime("%d-%b-%y")
        today_ts              = pd.Timestamp.today().normalize()
        bills["due_in_days"]  = (bills["due_dt"] - today_ts).dt.days.fillna(0).astype(int)
        all_pending           = bills[bills["pending_amount"] > 0]

        onacct      = all_pending[all_pending["invoice_no"].str.contains("on account", case=False, na=False)]
        unalloc_pdf = float(onacct["pending_amount"].sum()) if not onacct.empty else 0.0
        if bal_val is not None:
            bills_sum = float(all_pending["pending_amount"].sum())
            ladv = max(0.0, bills_sum - abs(bal_val)) if bal_val < 0 else 0.0
            if ladv > unalloc_pdf:
                unalloc_pdf = ladv

        due_bills = all_pending[
            (all_pending["due_in_days"] <= 0) &
            (~all_pending["invoice_no"].str.contains("on account", case=False, na=False))
        ]
        total_due = float(due_bills["pending_amount"].sum())

        for _, b in due_bills.iterrows():
            days  = int(b.get("aging_days", 0))
            amt   = float(b.get("pending_amount", 0))
            dd    = int(b.get("due_in_days", 0))
            idate = str(b.get("invoice_date", "—"))
            dstr  = str(b.get("due_date_str", "—"))
            inv   = str(b.get("invoice_no", "—"))
            bg    = "#fee2e2" if days > 90 else "#fef3c7" if days > 30 else "#fff"
            sc    = "#dc2626" if dd < 0 else "#d97706" if dd <= 7 else "#16a34a"
            due_rows_html += (
                '<tr style="background:' + bg + ';">'
                '<td>' + idate + '</td>'
                '<td>' + dstr + '</td>'
                '<td style="font-family:monospace;">' + inv + '</td>'
                '<td style="text-align:right;font-weight:bold;color:#991b1b;">&#8377;' + f"{amt:,.0f}" + '</td>'
                '<td style="text-align:center;font-weight:bold;color:' + sc + ';">' + str(days) + 'd</td>'
                '</tr>'
            )

    for _, r in pdc_df.iterrows():
        chq  = str(r.get("instrument_date") or r.get("cheque_date") or "—")
        vch  = str(r.get("voucher_number", "—") or "—")
        inst = str(r.get("instrument_number") or "")
        bills = str(r.get("bill_refs") or "")
        narr = str(r.get("narration", "—") or "—")
        detail = bills if bills else narr
        if inst:
            detail = (("Chq " + inst + " · ") if detail else ("Chq " + inst)) + (detail or "")
        amt  = float(r.get("amount", 0) or 0)
        pdc_rows_html += (
            '<tr>'
            '<td style="color:#0f766e;font-weight:600;">' + chq + '</td>'
            '<td style="font-family:monospace;">' + vch + '</td>'
            '<td>' + (detail or "—") + '</td>'
            '<td style="text-align:right;color:#0f766e;font-weight:bold;">&#8377;' + f"{amt:,.0f}" + '</td>'
            '</tr>'
        )

    final_due  = max(0.0, total_due - pdc_total - unalloc_pdf)
    pdc_count  = len(pdc_df) if not pdc_df.empty else 0
    today_str  = date.today().strftime("%d %b %Y")
    today_str2 = date.today().strftime("%d-%b-%Y")

    mob_html    = ('<div style="font-size:12px;font-weight:800;color:#dc2626;margin-top:3px;">&#128241; ' + str(pdf_mobile_raw or '') + '</div>') if pdf_mobile_raw else ""
    ag_mob_html = ('<div style="font-size:10px;color:#0f766e;font-weight:700;margin-top:2px;">&#128241; ' + str(agency_mob_pdf or '') + '</div>') if agency_mob_pdf else ""
    # Ensure all string vars are not None
    pdf_agency  = str(pdf_agency or "—")
    pdf_state   = str(pdf_state or "—")
    bank_name   = str(bank_name or "")
    bank_acc    = str(bank_acc or "")
    bank_ifsc   = str(bank_ifsc or "")
    bank_branch = str(bank_branch or "")
    bank_holder = str(bank_holder or "")
    upi_id      = str(upi_id or "")
    due_empty   = '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:12px;">No overdue bills</td></tr>'
    qr_b64      = _load_qr()
    qr_img_tag  = ('<img src="data:image/png;base64,' + qr_b64 + '" width="130" height="130" style="border-radius:8px;border:2px solid #86efac;">') if qr_b64 else '<div style="width:130px;height:130px;background:#f0fdf4;border:2px dashed #86efac;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:9px;color:#16a34a;">QR unavailable</div>'

    pdc_section = (
        '<div class="st">&#127974; PDC Cheques (' + str(pdc_count) + ' cheque(s) &middot; &#8377;' + f"{pdc_total:,.0f}" + ')</div>'
        '<table><thead><tr class="tt"><th>Instrument Date</th><th>Voucher No</th><th>Settled Invoices / Chq</th><th style="text-align:right;">Amount</th></tr></thead>'
        '<tbody>' + pdc_rows_html + '</tbody>'
        '<tfoot><tr style="background:#f0fdf4;font-weight:bold;">'
        '<td colspan="3" style="text-align:right;color:#0f766e;">TOTAL PDC</td>'
        '<td style="text-align:right;color:#0f766e;font-size:13px;">&#8377;' + f"{pdc_total:,.0f}" + '</td>'
        '</tr></tfoot></table>'
    ) if pdc_rows_html else ""

    html = (
        "<!DOCTYPE html><html><head><meta charset=\"UTF-8\">"
        "<style>"
        "body{font-family:Arial,sans-serif;font-size:12px;color:#1e293b;padding:20px;background:#fff;}"
        ".hdr{display:flex;align-items:flex-start;justify-content:space-between;border-bottom:3px solid #185fa5;padding-bottom:12px;margin-bottom:14px;}"
        ".co{font-size:20px;font-weight:900;color:#185fa5;}"
        ".cs{font-size:10px;color:#64748b;margin-top:2px;}"
        ".pbox{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;margin-bottom:10px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px;}"
        ".pl{font-size:8px;font-weight:bold;color:#94a3b8;text-transform:uppercase;}"
        ".pv{font-size:12px;font-weight:700;color:#0f172a;margin-top:2px;}"
        ".netbox{background:#fee2e2;border:1px solid #fca5a5;border-radius:8px;padding:12px 16px;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;}"
        ".nl{font-size:9px;font-weight:bold;color:#dc2626;text-transform:uppercase;}"
        ".nv{font-size:28px;font-weight:900;color:#991b1b;line-height:1;}"
        ".ns{font-size:11px;color:#64748b;margin-top:4px;}"
        ".st{font-size:9px;font-weight:800;color:#475569;text-transform:uppercase;margin:10px 0 4px;border-left:3px solid #185fa5;padding-left:6px;}"
        "table{width:100%;border-collapse:collapse;margin-bottom:10px;font-size:11px;}"
        "th{background:#1e293b;color:#fff;padding:7px 8px;text-align:left;font-size:9px;text-transform:uppercase;}"
        "td{padding:6px 8px;border-bottom:1px solid #f1f5f9;}"
        ".tt{background:#0f766e;}"
        ".bbox{background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:10px 14px;display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px;}"
        ".bt{font-size:9px;font-weight:bold;color:#16a34a;text-transform:uppercase;margin-bottom:5px;}"
        ".br{display:flex;gap:6px;margin-bottom:3px;font-size:11px;}"
        ".bk{color:#64748b;font-weight:600;min-width:80px;}"
        ".bv{color:#0f172a;font-weight:700;}"
        ".cbox{background:#dc2626;border-radius:8px;padding:12px;margin-bottom:10px;text-align:center;font-size:15px;font-weight:900;color:#fff;}"
        ".footer{padding-top:8px;border-top:1px solid #e2e8f0;font-size:9px;color:#94a3b8;text-align:center;}"
        "</style></head><body>"
        + '<div class="hdr"><div><div class="co">RANGRUCHI FASHION PVT LTD</div>'
        + '<div class="cs">Party Ledger Statement &middot; As on ' + today_str + '</div>'
        + '<div class="cs">Email: rangruchifashionpvtltd@gmail.com</div></div>'
        + '<div style="text-align:right;"><div style="font-size:10px;color:#64748b;">Statement Date</div>'
        + '<div style="font-size:14px;font-weight:800;color:#185fa5;">' + today_str2 + '</div></div></div>'
        + '<div class="pbox">'
        + '<div><div class="pl">Party Name</div><div class="pv" style="color:#185fa5;font-size:13px;">' + selected + '</div>' + mob_html + '</div>'
        + '<div><div class="pl">Agency</div><div class="pv">' + pdf_agency + '</div>' + ag_mob_html
        + '<div class="pl" style="margin-top:4px;">State</div><div class="pv">' + pdf_state + '</div></div>'
        + '<div><div class="pl">Bills Due</div><div class="pv" style="color:#991b1b;">&#8377;' + f"{total_due:,.0f}" + '</div>'
        + '<div class="pl" style="margin-top:4px;">Unallocated</div><div class="pv" style="color:#b45309;">&#8377;' + f"{unalloc_pdf:,.0f}" + '</div></div>'
        + '<div><div class="pl">PDC Cheques</div><div class="pv" style="color:#0f766e;">&#8377;' + f"{pdc_total:,.0f}" + '</div>'
        + '<div class="pl" style="margin-top:4px;">Credit Period</div><div class="pv">' + str(credit_period) + ' Days</div></div>'
        + '</div>'
        + '<div class="netbox"><div><div class="nl">Net Due Amount</div>'
        + '<div class="nv">&#8377;' + f"{final_due:,.0f}" + '</div>'
        + '<div class="ns">&#8377;' + f"{total_due:,.0f}" + ' &minus; PDC &#8377;' + f"{pdc_total:,.0f}" + ' &minus; Unallocated &#8377;' + f"{unalloc_pdf:,.0f}" + '</div></div>'
        + '<div style="text-align:right;"><div style="font-size:9px;color:#64748b;">Credit Period</div>'
        + '<div style="font-size:16px;font-weight:800;color:#dc2626;">' + str(credit_period) + ' Days</div></div></div>'
        + '<div class="st">&#128203; Due Bills (Past Credit Period)</div>'
        + '<table><thead><tr><th>Invoice Date</th><th>Due Date</th><th>Invoice No</th>'
        + '<th style="text-align:right;">Pending</th><th style="text-align:center;">Overdue</th></tr></thead>'
        + '<tbody>' + (due_rows_html if due_rows_html else due_empty) + '</tbody>'
        + '<tfoot><tr style="background:#fee2e2;font-weight:bold;">'
        + '<td colspan="3" style="text-align:right;color:#991b1b;">TOTAL BILLS DUE</td>'
        + '<td style="text-align:right;color:#991b1b;font-size:13px;">&#8377;' + f"{total_due:,.0f}" + '</td><td></td>'
        + '</tr></tfoot></table>'
        + pdc_section
        + '<div class="bbox"><div style="flex:1;"><div class="bt">&#127970; Payment / Bank Details</div>'
        + '<div class="br"><span class="bk">Bank:</span><span class="bv">' + bank_name + '</span></div>'
        + '<div class="br"><span class="bk">A/C Holder:</span><span class="bv">' + bank_holder + '</span></div>'
        + '<div class="br"><span class="bk">Account No:</span><span class="bv">' + bank_acc + '</span></div>'
        + '<div class="br"><span class="bk">IFSC:</span><span class="bv">' + bank_ifsc + '</span></div>'
        + '<div class="br"><span class="bk">Branch:</span><span class="bv">' + bank_branch + '</span></div>'
        + '<div class="br"><span class="bk">UPI ID:</span><span class="bv">' + upi_id + '</span></div></div>'
        + '<div style="text-align:center;flex-shrink:0;">' + qr_img_tag
        + '<div style="font-size:9px;color:#16a34a;margin-top:4px;font-weight:bold;">Scan to Pay</div>'
        + '<div style="font-size:8px;color:#64748b;">' + upi_id + '</div></div></div>'
        + '<div class="cbox">&#128222; For any query contact &nbsp; 84018 13571</div>'
        + '<div class="footer">RANGRUCHI FASHION PVT LTD &middot; RecoveryOS &middot; Confidential &middot;'
        + ' <a href="javascript:window.print()">Print this page</a></div>'
        + '</body></html>'
    )

    import re as _re
    fname = _re.sub(r"[^A-Za-z0-9_\-]", "_", selected[:30])
    print_html = html + f"""<script>
window.onload = function() {{
    document.title = "Ledger_{fname}";
    window.print();
}};
</script>"""
    response = make_response(print_html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response
