"""Read-only diagnostics for missing agency names and contact numbers."""
import html
import re
from agency_contact_sync import MASTER, _blocks, _tag, _udf, _phone, _contact
from db import query_df

def _values(block):
    fields = []
    for match in re.finditer(r"<(?:UDF[:_])?([A-Za-z][A-Za-z0-9_]*)\b[^>]*>([^<>]{1,180})</", block, re.I):
        key = match.group(1).upper()
        value = html.unescape(match.group(2).strip())
        if not value or value.lower() in ("yes", "no", "true", "false"):
            continue
        if any(x in key for x in ("BROKER","AGENCY","AGENT","MOBILE","PHONE","CONTACT","WHATSAPP")):
            fields.append((key, value[:90]))
    return fields[:20]

def report(limit=250):
    df = query_df("""SELECT party_name, COALESCE(agent_name,'') agent_name,
        COALESCE(agency_name,'') agency_name,
        COALESCE(party_mobile,'') party_mobile
        FROM tickets
        WHERE COALESCE(TRIM(agent_name),'')=''
          OR COALESCE(TRIM(agency_name),'')=''
          OR COALESCE(TRIM(party_mobile),'')=''
        ORDER BY party_name LIMIT %s""", (limit,))
    rows = df.to_dict("records")
    indexed = {re.sub(r'\s+', ' ', str(r["party_name"])).strip().upper():r for r in rows}
    for r in rows:
        r["candidate_agency"] = ""
        r["candidate_agent"] = ""
        r["candidate_contact"] = ""
        r["source_fields"] = []
        r["status"] = "No matching XML ledger"
    if not indexed:
        return rows, "No unresolved tickets"
    import os
    if not os.path.isfile(MASTER):
        return rows, "Master.xml not found on this computer"
    for typ, name, block in _blocks(MASTER):
        if typ != "LEDGER":
            continue
        key = re.sub(r'\s+', ' ', name).strip().upper()
        key = re.sub(r'\s*\(RR\d+\)\s*$', '', key)
        row = indexed.get(key)
        if row is None:
            continue
        row["candidate_agency"] = _udf(block, ("BMSTLEDAGENCYNAMEUDF",)) or ""
        row["candidate_agent"] = _udf(block, ("BEIBROKERNAMEUDF",)) or ""
        row["candidate_contact"] = _contact(block)
        row["source_fields"] = _values(block)
        row["status"] = "Review candidates" if row["source_fields"] or any(
            row[k] for k in ("candidate_agency","candidate_agent","candidate_contact")
        ) else "No alternate fields found"
    return rows, "Read-only report; candidate values require review"
