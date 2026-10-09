"""Targeted, non-destructive agency/contact refresh from the local Tally Master.xml.
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

def _blocks(path):
    with open(path, "rb") as fp:
        head = fp.read(4)
    enc = "utf-16-le" if head[:2] == b"\xff\xfe" or (len(head)>1 and head[1]==0) else "utf-16-be" if head[:2] == b"\xfe\xff" else "utf-8"
    buf = ""
    with io.open(path, encoding=enc, errors="ignore") as fp:
        while True:
            chunk = fp.read(2_000_000)
            if not chunk:
                break
            buf += chunk
            end = 0
            for match in BLOCK.finditer(buf):
                yield match.group(1).upper(), html.unescape(match.group(2)), match.group(3)
                end = match.end()
            if end:
                buf = buf[end:]
            if len(buf)>20_000_000:
                raise ValueError("Unexpectedly long XML block; sync aborted without changes")
        for match in BLOCK.finditer(buf):
            yield match.group(1).upper(), html.unescape(match.group(2)), match.group(3)

def _columns(cur, table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s", (table,))
    return {r[0] for r in cur.fetchall()}

def run_targeted_sync(kind):
    if kind not in ("agency", "contact"):
        raise ValueError("Unknown sync type")
    if not os.path.isfile(MASTER):
        raise FileNotFoundError("Master.xml not found on the application computer. Export the latest Tally masters first.")
    parties, groups = {}, {}
    for typ, name, block in _blocks(MASTER):
        if typ == "GROUP":
            group_phone = _phone(_udf(block, UDF_MOBILE)) or _contact(block)
            if group_phone:
                groups[name.upper()] = (name, group_phone)
            continue
        agency = _udf(block, UDF_AGENCY)
        if not agency:
            parent = _tag(block, "PARENT")
            if parent.upper() in groups:
                agency = groups[parent.upper()][0]
        phone = _contact(block)
        if agency or phone:
            parties[name.upper()] = (name, agency, phone)
    conn = get_conn()
    totals = {"parties":len(parties), "groups":len(groups), "party_updates":0, "ticket_updates":0, "agency_updates":0}
    try:
        with conn.cursor() as cur:
            tpm = _columns(cur, "tally_party_master")
            tickets = _columns(cur, "tickets")
            agency_cols = _columns(cur, "tally_agency_master")
            if kind == "agency":
                if {"party_name","agency_name"} <= tpm:
                    for name, agency, phone in parties.values():
                        if agency:
                            cur.execute("""UPDATE tally_party_master SET agency_name=%s
                                WHERE UPPER(TRIM(party_name))=%s
                                AND COALESCE(TRIM(agency_name),'')=''""", (agency,name.upper()))
                            totals["party_updates"] += cur.rowcount
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
