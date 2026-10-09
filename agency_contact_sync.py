"""Targeted, non-destructive agency/contact refresh from live TallyPrime.
No full financial sync. Existing nonblank values are preserved.
"""
import html
import io
import os
import re
from db import get_conn, release_conn

ROOT = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(ROOT, "Master.xml")
BLOCK = re.compile(r'<(LEDGER|GROUP)\s+NAME="([^"]*)"[^>]*>(.*?)</\1>', re.I | re.S)
UDF_AGENCY = ("BMSTLEDAGENCYNAMEUDF", "BEIBROKERNAMEUDF")
UDF_MOBILE = ("BGRPBROKERGROUPMOUDF",)

def _tag(block, name):
    m = re.search(r"<" + re.escape(name) + r"\b[^>]*>(.*?)</" + re.escape(name) + r">", block, re.I | re.S)
    return html.unescape(re.sub(r"<[^>]*>", "", m.group(1)).strip()) if m else ""

def _udf(block, names):
    for name in names:
        m = re.search(r"<UDF[:_]" + name + r"\b[^>]*>(.*?)</UDF[:_]" + name + r">", block, re.I | re.S)
        if m:
            value = html.unescape(re.sub(r"<[^>]*>", "", m.group(1)).strip())
            if value:
                return value
    return ""

def _phone(value):
    for candidate in re.split(r"[,;/&]", str(value or "")):
        digits = re.sub(r"\D", "", candidate)
        if len(digits) >= 10:
            return digits[-10:]
    return ""

def _contact(block):
    contacts = re.findall(r"<LEDGERCONTACTLIST\.LIST>(.*?)</LEDGERCONTACTLIST\.LIST>", block, re.I | re.S)
    for part in contacts:
        if "mobile" in _tag(part, "NAME").lower():
            number = _phone(_tag(part, "PHONENUMBER") or _tag(part, "MOBILENO"))
            if number:
                return number
    options = [_tag(block, "LEDGERMOBILE"), _tag(block, "MOBILENO"), _tag(block, "MOBILE")]
    options += [_tag(part, "PHONENUMBER") for part in contacts]
    options.append(_tag(block, "PHONENUMBER"))
    options.append(_udf(block, ("MIWHATSAPPNUM",)))
    return next((p for raw in options if (p := _phone(raw))), "")

def _live_collection(kind):
    """Fetch current Tally masters over HTTP; no local Master.xml required."""
    import requests
    import xml.etree.ElementTree as ET
    from config import TALLY_URL
    fields = (
        "Name,Parent,LedgerMobile,Mobile,PhoneNumber,LedgerContactList,"
        "BMstLedAgencyNameUdf,BEIBrokerNameUdf,MIWhatsAppNum"
        if kind == "Ledger" else
        "Name,Parent,BGRPBrokerGroupMoUdf,Mobile,PhoneNumber"
    )
    company = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"
    xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>
<TYPE>Collection</TYPE><ID>RRTarget{kind}</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY></STATICVARIABLES>
<TDL><TDLMESSAGE><COLLECTION NAME="RRTarget{kind}"><TYPE>{kind}</TYPE>
<FETCH>{fields}</FETCH></COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""
    resp = requests.post(TALLY_URL, data=xml.encode("utf-8"),
        headers={"Content-Type":"application/xml","Accept-Encoding":"identity"}, timeout=120)
    resp.raise_for_status()
    raw = re.sub(r'&#(?:x[0-9a-fA-F]+|[0-9]+);', '', resp.text)
    root = ET.fromstring(raw)
    if root.findtext(".//STATUS") == "0":
        raise RuntimeError("Tally reported a failed export")
    nodes = root.findall(".//" + kind.upper())
    if not nodes:
        raise RuntimeError("Tally returned no " + kind + " records; no database changes made")
    for node in nodes:
        name = html.unescape(node.attrib.get("NAME","").strip())
        if name:
            yield name, ET.tostring(node,encoding="unicode")

def _columns(cur, table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s", (table,))
    return {r[0] for r in cur.fetchall()}

def run_targeted_sync(kind):
    if kind not in ("agency", "contact"):
        raise ValueError("Unknown sync type")
    parties, groups = {}, {}
    for name, block in _live_collection("Group"):
        group_phone = _phone(_udf(block, UDF_MOBILE)) or _contact(block)
        if group_phone:
            groups[name.upper()] = (name, group_phone)
    for name, block in _live_collection("Ledger"):
        agency = _udf(block, UDF_AGENCY)
        if not agency:
            parent = _tag(block, "PARENT")
            if parent.upper() in groups:
                agency = groups[parent.upper()][0]
        phone = _contact(block)
        if agency or phone:
            parties[name.upper()] = (name, agency, phone, _udf(block, ("BEIBROKERNAMEUDF",)))
    if not parties:
        raise RuntimeError("No ledger contact or agency fields returned; database unchanged")
    conn = get_conn()
    totals = {"parties":len(parties), "groups":len(groups), "party_updates":0, "ticket_updates":0, "agency_updates":0}
    try:
        with conn.cursor() as cur:
            tpm = _columns(cur, "tally_party_master")
            tickets = _columns(cur, "tickets")
            agency_cols = _columns(cur, "tally_agency_master")
            if kind == "agency":
                if {"party_name","agency_name"} <= tpm:
                    for name, agency, phone, agent in parties.values():
                        if agency:
                            cur.execute("""UPDATE tally_party_master SET agency_name=%s
                                WHERE UPPER(TRIM(party_name))=%s
                                AND COALESCE(TRIM(agency_name),'')=''""", (agency,name.upper()))
                            totals["party_updates"] += cur.rowcount
                if {"party_name", "agent_name"} <= tickets:
                    for name, agency, phone, agent in parties.values():
                        if agent:
                            cur.execute("""UPDATE tickets SET agent_name=%s
                                WHERE UPPER(TRIM(party_name))=%s
                                AND COALESCE(TRIM(agent_name),'')=''""", (agent, name.upper()))
                            totals["ticket_updates"] += cur.rowcount
                if {"party_name","agency_name"} <= tickets and {"party_name","agency_name"} <= tpm:
                    cur.execute("""UPDATE tickets t SET agency_name=p.agency_name FROM tally_party_master p
                        WHERE UPPER(TRIM(t.party_name))=UPPER(TRIM(p.party_name))
                        AND COALESCE(TRIM(t.agency_name),'')=''
                        AND COALESCE(TRIM(p.agency_name),'')<>''""")
                    totals["ticket_updates"] += cur.rowcount
                phone_col = "agency_mobile" if "agency_mobile" in agency_cols else "mobile" if "mobile" in agency_cols else None
                if phone_col and "agency_name" in agency_cols:
                    for name, phone in groups.values():
                        cur.execute(f"""UPDATE tally_agency_master SET {phone_col}=%s
                            WHERE UPPER(TRIM(agency_name))=%s
                            AND COALESCE(TRIM({phone_col}),'')=''""", (phone,name.upper()))
                        totals["agency_updates"] += cur.rowcount
            else:
                if {"party_name","mobile"} <= tpm:
                    for name, agency, phone in parties.values():
                        if phone:
                            cur.execute("""UPDATE tally_party_master SET mobile=%s
                                WHERE UPPER(TRIM(party_name))=%s AND COALESCE(TRIM(mobile),'')=''""",
                                (phone,name.upper()))
                            totals["party_updates"] += cur.rowcount
                if {"party_name","party_mobile"} <= tickets and {"party_name","mobile"} <= tpm:
                    cur.execute("""UPDATE tickets t SET party_mobile=p.mobile FROM tally_party_master p
                        WHERE UPPER(TRIM(t.party_name))=UPPER(TRIM(p.party_name))
                        AND COALESCE(TRIM(t.party_mobile),'')=''
                        AND COALESCE(TRIM(p.mobile),'')<>''""")
                    totals["ticket_updates"] += cur.rowcount
        conn.commit()
        return totals
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)
