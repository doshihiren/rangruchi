"""Targeted, non-destructive agency/contact refresh from live TallyPrime.
No full financial sync. Agency values are fill-only; Contact Sync refreshes verified changed mobiles.
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
    # Preserve valid numeric XML entities. Strip only references to forbidden
    # XML 1.0 codepoints; escaping all entities corrupts legal text.
    raw = resp.text.lstrip(chr(0xFEFF))
    def valid_entity(match):
        value = match.group(1)
        try:
            cp = int(value[1:], 16) if value.lower().startswith("x") else int(value)
            valid = cp in (9, 10, 13) or 0x20 <= cp <= 0xD7FF or 0xE000 <= cp <= 0xFFFD or 0x10000 <= cp <= 0x10FFFF
            return match.group(0) if valid else ""
        except ValueError:
            return ""
    raw = re.sub(r"&#(x[0-9a-fA-F]+|[0-9]+);", valid_entity, raw)
    raw = raw.replace("UDF:", "UDF_")
    raw = "".join(ch for ch in raw if ord(ch) in (9, 10, 13) or ord(ch) >= 32)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError(f"Tally returned malformed XML ({exc}); no changes made") from exc
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

def _normalize_party(name):
    """Normalize exact party identity without fuzzy matching."""
    value = html.unescape(str(name or "")).strip()
    value = re.sub(r"\\s*\\(RR\\d+\\)\\s*$", "", value, flags=re.I)
    value = re.sub(r"\\s+", " ", value).strip().upper()
    return value

def _match_missing_ticket_parties(cur, parties):
    """Find unique, exact party-name matches before touching any ticket."""
    cur.execute("SELECT DISTINCT party_name FROM tickets WHERE COALESCE(TRIM(agency_name),'')=''")
    names = [str(r[0]) for r in cur.fetchall()]
    mapped = {}
    ambiguous = set()
    for value in parties.values():
        key = _normalize_party(value[0])
        if key in mapped and mapped[key][0] != value[0]:
            ambiguous.add(key)
        else:
            mapped[key] = value
    updates = []
    for ticket_name in names:
        key = _normalize_party(ticket_name)
        match = mapped.get(key)
        if match and key not in ambiguous and match[1]:
            updates.append((ticket_name, match[1]))
    return updates

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
                # Fill tickets directly from their live Tally ledger UDF.
                # This avoids relying on a potentially stale party-master row.
                if {"party_name", "agency_name"} <= tickets:
                    for ticket_name, agency in _match_missing_ticket_parties(cur, parties):
                        cur.execute("""UPDATE tickets SET agency_name=%s
                            WHERE party_name=%s AND COALESCE(TRIM(agency_name),'')=''""",
                            (agency, ticket_name))
                        totals["ticket_updates"] += cur.rowcount
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
                # Insert missing agency-master rows only for exact normalized
                # matches to names on active tickets. Never use fuzzy guesses.
                if {"agency_name", "mobile"} <= agency_cols and {"agency_name"} <= tickets:
                    cur.execute("""SELECT DISTINCT agency_name FROM tickets
                        WHERE COALESCE(TRIM(agency_name),'')<>''""")
                    used_names = [row[0] for row in cur.fetchall()]
                    normalized_groups = {}
                    collisions = set()
                    for group_name, phone in groups.values():
                        key = _normalize_party(group_name)
                        if key in normalized_groups:
                            collisions.add(key)
                        normalized_groups[key] = phone
                    for agency_name in used_names:
                        key = _normalize_party(agency_name)
                        if key in ("CASH", "SELF", "DIRECT") or key in collisions:
                            continue
                        phone = normalized_groups.get(key)
                        if not phone:
                            continue
                        # Respect existing records even when casing differs.
                        cur.execute("""SELECT id, mobile FROM tally_agency_master
                            WHERE UPPER(TRIM(agency_name))=%s""", (key,))
                        matched = cur.fetchall()
                        if len(matched) > 1:
                            continue
                        if matched:
                            if not matched[0][1] or not str(matched[0][1]).strip():
                                cur.execute("""UPDATE tally_agency_master SET mobile=%s,
                                    last_synced_at=NOW() WHERE id=%s
                                    AND COALESCE(TRIM(mobile),'')=''""",
                                    (phone, matched[0][0]))
                                totals["agency_updates"] += cur.rowcount
                        else:
                            cur.execute("""INSERT INTO tally_agency_master
                                (agency_name,mobile,last_synced_at)
                                VALUES (%s,%s,NOW()) ON CONFLICT (agency_name) DO NOTHING""",
                                (agency_name,phone))
                            totals["agency_updates"] += cur.rowcount
            else:
                # Contact Sync is an authoritative refresh, not just a blank
                # filler. Match unique live Tally ledgers exactly after the
                # same harmless name normalization used for agency mapping.
                # Never overwrite a stored number with a blank or guess.
                by_name = {}
                ambiguous = set()
                for name, agency, phone, agent in parties.values():
                    if not phone:
                        continue
                    key = _normalize_party(name)
                    if key in by_name and by_name[key] != phone:
                        ambiguous.add(key)
                    else:
                        by_name[key] = phone
                for key in ambiguous:
                    by_name.pop(key, None)
                if {"party_name", "mobile"} <= tpm:
                    cur.execute("SELECT DISTINCT party_name FROM tally_party_master")
                    for (db_name,) in cur.fetchall():
                        phone = by_name.get(_normalize_party(db_name))
                        if phone:
                            cur.execute("""UPDATE tally_party_master SET mobile=%s
                                WHERE party_name=%s AND mobile IS DISTINCT FROM %s""",
                                (phone, db_name, phone))
                            totals["party_updates"] += cur.rowcount
                if {"party_name", "party_mobile"} <= tickets:
                    cur.execute("SELECT DISTINCT party_name FROM tickets")
                    for (db_name,) in cur.fetchall():
                        phone = by_name.get(_normalize_party(db_name))
                        if phone:
                            cur.execute("""UPDATE tickets SET party_mobile=%s
                                WHERE party_name=%s AND party_mobile IS DISTINCT FROM %s""",
                                (phone, db_name, phone))
                            totals["ticket_updates"] += cur.rowcount
        conn.commit()
        return totals
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)
