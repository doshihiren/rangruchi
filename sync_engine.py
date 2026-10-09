# ============================================================
# sync_engine.py  –  Tally → PostgreSQL sync engine
# ============================================================
import requests
import xml.etree.ElementTree as ET
import logging
import re
from datetime import datetime
from config import TALLY_URL as CONFIG_TALLY_URL
from db import execute, executemany, fetchone, query_df
from tally_guard import tally_alive, safe_replace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/sync.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
TALLY_HEADERS = {"Content-Type": "application/xml"}

TALLY_URL = "http://192.168.1.19:9000"

# Use the confirmed live Tally address for this project.  The old config
# pointed to 192.168.1.34, which caused sync requests to time out after the
# server/Tally PC was moved to 192.168.1.19.

def tally_alive():
    try:
        resp = requests.get(TALLY_URL, timeout=5)
        return resp.status_code == 200
    except Exception:
        try:
            resp = requests.post(
                TALLY_URL,
                data=b"<ENVELOPE><HEADER><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>Ledger</ID></HEADER><BODY><DESC><TDL><TDLMESSAGE><COLLECTION NAME=\"PingLedgers\"><TYPE>Ledger</TYPE><FETCH>Name</FETCH></COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>",
                headers=TALLY_HEADERS, timeout=5
            )
            return resp.ok
        except Exception:
            return False


def _clean_xml(text):
    def fix_hex(m):
        try:
            cp = int(m.group(1), 16)
            if cp in (0x9,0xA,0xD): return m.group(0)
            if 0x20<=cp<=0xD7FF:    return m.group(0)
            if 0xE000<=cp<=0xFFFD:  return m.group(0)
            return ''
        except: return ''
    def fix_dec(m):
        try:
            cp = int(m.group(1))
            if cp in (9,10,13): return m.group(0)
            if 0x20<=cp<=0xD7FF: return m.group(0)
            return ''
        except: return ''
    text = re.sub(r'&#x([0-9a-fA-F]+);', fix_hex, text)
    text = re.sub(r'&#([0-9]+);', fix_dec, text)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    return text

def _post_xml(xml):
    resp = requests.post(TALLY_URL, data=xml, headers=TALLY_HEADERS, timeout=300)
    resp.raise_for_status()
    return _clean_xml(resp.text)

def _log_sync(sync_type, records, status, error=None):
    execute("INSERT INTO sync_log (sync_type,records_synced,status,error_msg) VALUES(%s,%s,%s,%s)",
            (sync_type, records, status, error))


# ── 1. Outstanding ────────────────────────────────────────────
OUTSTANDING_XML = """<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>LedgerCollection</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)</SVCURRENTCOMPANY>
</STATICVARIABLES>
<TDL><TDLMESSAGE><COLLECTION NAME="LedgerCollection">
<TYPE>Ledger</TYPE><FETCH>Name,ClosingBalance,Parent,PhoneNumber,Mobile,LedgerContactList,UDF:BMstLedAgencyNameUdf,UDF:BEIBrokerNameUdf,UDF:BGRPBrokerGroupMoUdf,UDF:BMstLedPlaceUdf</FETCH>
</COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""

def sync_outstanding():
    logger.info("Syncing outstanding...")
    try:
        root = ET.fromstring(_post_xml(OUTSTANDING_XML))
        rows = []; now = datetime.now()
        for led in root.findall(".//LEDGER"):
            try:
                name = re.sub(r'\(RR\d+\)\s*$', '', led.get("NAME","").strip()).strip()
                cb   = led.findtext("CLOSINGBALANCE","").replace(",","").strip()
                if not name or not cb: continue
                bal  = float(cb)
                if bal == 0: continue
                rows.append((name, bal, now))
                if "SANJAY TRADERS BHAGALPUR" in name.upper():
                    logger.info(f"TALLY CHECK: {name} ClosingBalance={bal}")
            except: pass
        written = safe_replace("outstanding",
            "INSERT INTO outstanding(party_name,balance,synced_at) VALUES(%s,%s,%s)",
            rows)
        if written < 0:
            _log_sync("outstanding", 0, "Skipped", "suspicious row count - old data kept")
            return 0
        _log_sync("outstanding", len(rows), "Success")
        logger.info(f"Outstanding: {len(rows)} records")
        return len(rows)
    except Exception as e:
        _log_sync("outstanding", 0, "Failed", str(e))
        logger.error(f"Outstanding error: {e}")
        raise


# ── 2. Billwise ───────────────────────────────────────────────


AGENT_AGENCY_XML = """<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>BillCollection</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES>
<TDL><TDLMESSAGE><COLLECTION NAME="BillCollection">
<TYPE>Ledger</TYPE>
<FETCH>Name, BillAllocations.List,PhoneNumber,Mobile,LedgerContactList,UDF:BMstLedAgencyNameUdf,UDF:BEIBrokerNameUdf,UDF:BGRPBrokerGroupMoUdf,UDF:BMstLedPlaceUdf</FETCH>
</COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""

def sync_billwise():
    logger.info("Syncing billwise (native Bills Receivable report)...")
    try:
        company = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"  # hardcoded - always sync correct company
        now = datetime.now()
        today = now.strftime("%Y%m%d")
        fy_start_year = now.year if now.month >= 4 else now.year - 1
        from_date = f"{fy_start_year}0401"

        billwise_xml = f"""<ENVELOPE><HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
<BODY><EXPORTDATA><REQUESTDESC><REPORTNAME>Bills Receivable</REPORTNAME>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>
<SVFROMDATE>{from_date}</SVFROMDATE>
<SVTODATE>{today}</SVTODATE>
<EXPLODEFLAG>Yes</EXPLODEFLAG>
</STATICVARIABLES></REQUESTDESC></EXPORTDATA></BODY></ENVELOPE>"""

        resp = requests.post(TALLY_URL, data=billwise_xml,
                             headers={"Content-Type": "application/xml", "Accept-Encoding": "identity"},
                             timeout=180)
        raw_text = _clean_xml(resp.text)
        root = ET.fromstring(raw_text)

        rows = []
        now_ts = datetime.now()
        all_children = list(root)
        i = 0
        while i < len(all_children):
            el = all_children[i]
            if el.tag == "BILLFIXED":
                try:
                    bill_date_raw = el.findtext("BILLDATE", "")
                    inv_no        = el.findtext("BILLREF", "")
                    party_name    = el.findtext("BILLPARTY", "")
                    if party_name:
                        party_name = re.sub(r'\(RR\d+\)\s*$', '', re.sub(r'\\s+', ' ', party_name).strip()).strip()

                    pending = 0.0
                    overdue_days = None
                    j = i + 1
                    while j < len(all_children):
                        sib = all_children[j]
                        if sib.tag == "BILLFIXED":
                            break
                        if sib.tag == "BILLCL" and sib.text:
                            pending = abs(float(sib.text.replace(",","").strip()))
                        if sib.tag == "BILLOVERDUE" and sib.text:
                            try:
                                overdue_days = int(sib.text.strip())
                            except Exception:
                                pass
                        j += 1

                    # bill_date_raw is already DD-Mon-YY format from this report
                    raw_date_stripped = bill_date_raw.strip() if bill_date_raw else ""
                    inv_date = None
                    if re.match(r'^\d{1,2}-[A-Za-z]{3}-\d{2}$', raw_date_stripped):
                        # normalize single-digit day to 2-digit
                        parts = raw_date_stripped.split('-')
                        inv_date = f"{parts[0].zfill(2)}-{parts[1]}-{parts[2]}"

                    if party_name and inv_date and pending > 0:
                        rows.append((party_name, inv_date, inv_no, overdue_days, pending, now_ts))
                except Exception:
                    pass
            i += 1

        written = safe_replace("billwise",
            """INSERT INTO billwise(party_name,invoice_date,invoice_no,overdue_days,pending_amount,synced_at)
               VALUES(%s,%s,%s,%s,%s,%s)""",
            rows)
        if written < 0:
            _log_sync("billwise", 0, "Skipped", "suspicious row count - old data kept")
            return 0

        updated_aa = 0
        try:
            aa_resp = requests.post(TALLY_URL, data=AGENT_AGENCY_XML,
                                    headers=TALLY_HEADERS, timeout=120)
            aa_clean = aa_resp.text.replace('UDF:', 'UDF_')
            aa_root = ET.fromstring(aa_clean)
            for led in aa_root.findall(".//LEDGER"):
                p_name = led.get("NAME","").strip()
                if p_name:
                    p_name = re.sub(r'\(RR\d+\)\s*$', '', p_name).strip()
                if not p_name:
                    continue
                agent = None
                agency = None
                for child in led.iter():
                    tag_upper = child.tag.upper()
                    if tag_upper.endswith("BEIBROKERNAMEUDF") and child.text and child.text.strip():
                        agent = child.text.strip()
                    if tag_upper.endswith("BEIBROKERGRPUDF") and child.text and child.text.strip():
                        agency = child.text.strip()
                if agent or agency:
                    try:
                        existing = fetchone("SELECT id FROM salesperson_mapping WHERE party_name=%s", (p_name,))
                        if existing:
                            execute("""UPDATE salesperson_mapping SET
                                agent_name=COALESCE(NULLIF(%s,''), agent_name),
                                agency_name=COALESCE(NULLIF(%s,''), agency_name)
                                WHERE party_name=%s""",
                                (agent or '', agency or '', p_name))
                        else:
                            execute("""INSERT INTO salesperson_mapping (party_name,agent_name,agency_name)
                                VALUES(%s,%s,%s)""", (p_name, agent, agency))
                        updated_aa += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Agent/Agency fetch error (non-blocking): {e}")

        _log_sync("billwise", len(rows), "Success")
        logger.info(f"Billwise: {len(rows)} records (exact Tally match), {updated_aa} parties got agent/agency data")
        return len(rows)
    except Exception as e:
        _log_sync("billwise", 0, "Failed", str(e))
        logger.error(f"Billwise error: {e}")
        raise


# ── 3. Ledger Masters (party details) ────────────────────────
LEDGER_XML = """<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>LedgerMastersCollection</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES>
<TDL><TDLMESSAGE><COLLECTION NAME="LedgerMastersCollection">
<TYPE>Ledger</TYPE>
<FETCH>Name,Parent,LedstateName,PartyGstin,LedgerMobile,Address,Pincode,BasicDueDateOfPymt,BillCreditPeriod,PhoneNumber,Mobile,UDF:BMstLedAgencyNameUdf,UDF:BEIBrokerNameUdf,UDF:BGRPBrokerGroupMoUdf,UDF:BMstLedPlaceUdf,LedgerContactList</FETCH>
</COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""

def sync_ledger_masters():
    logger.info("Syncing ledger masters (party details)...")
    try:
        xml_text = _post_xml(LEDGER_XML).replace('UDF:', 'UDF_')
        root = ET.fromstring(xml_text)

        rows = []
        for led in root.findall(".//LEDGER"):
            try:
                name = re.sub(r'\(RR\d+\)\s*$', '', led.get("NAME","").strip()).strip()
                if not name: continue
                parent  = led.findtext("PARENT","").strip()
                state   = led.findtext("LEDSTATENAME","").strip()
                gstin   = led.findtext("PARTYGSTIN","").strip()
                # Keep first mobile number only (Tally sometimes stores multiple)
                def _d10(v):
                    if not v:
                        return ""
                    d = re.sub(r'[^0-9]', '', re.split(r'[/,;&]', str(v))[0])
                    return d[-10:] if len(d) >= 10 else ""

                mobile = ""
                _fallback = ""
                for _cl in led.findall(".//LEDGERCONTACTLIST.LIST"):
                    _cn = (_cl.findtext("NAME", "") or "").lower()
                    _ph = _d10(_cl.findtext("PHONENUMBER", "") or _cl.findtext("MOBILENO", ""))
                    if not _ph:
                        continue
                    if "mobile" in _cn:
                        mobile = _ph
                        break
                    _fallback = _fallback or _ph
                if not mobile:
                    mobile = (_d10(led.findtext("LEDGERMOBILE", "")) or
                              _d10(led.findtext("MOBILENO", "")) or
                              _d10(led.findtext("PHONENUMBER", "")) or
                              _fallback)
                addr_el = led.findtext("ADDRESS","")
                addr    = addr_el.strip() if addr_el else ""
                pin     = led.findtext("PINCODE","").strip()

                place      = led.findtext("UDF_BMSTLEDPLACEUDF","").strip()
                def _udf(suffix):
                    for _ch in led.iter():
                        if _ch.tag.upper().replace(":", "_").endswith(suffix) \
                                and _ch.text and _ch.text.strip():
                            return _ch.text.strip()
                    return ""

                agency_nm  = _udf("BMSTLEDAGENCYNAMEUDF")
                agent_nm   = _udf("BEIBROKERNAMEUDF")
                agency_mob = _udf("BGRPBROKERGROUPMOUDF")
                try:
                    # BASICDUEDATEOFPYMT = per-party credit period (most accurate)
                    # BILLCREDITPERIOD = fallback
                    cp_raw = (led.findtext("BASICDUEDATEOFPYMT","") or
                              led.findtext("BILLCREDITPERIOD","") or "").strip()
                    m = re.search(r'(\d+)', cp_raw)
                    credit_days = int(m.group(1)) if m else None
                except:
                    credit_days = None
                rows.append((name, parent, state, gstin, mobile, addr, pin, place, agency_nm, agent_nm, agency_mob, credit_days))
            except: pass

        # Update salesperson_mapping - state, mobile, gstin, address only
        # (agent/agency/seller UDF fields not available via this method -
        #  preserved from any prior source, never overwritten with blank)
        for name, parent, state, gstin, mobile, addr, pin, place, agency_nm, agent_nm, agency_mob, credit_days in rows:
            try:
                existing = fetchone("SELECT id FROM salesperson_mapping WHERE party_name=%s", (name,))
                if existing:
                    if credit_days is not None:
                        execute("""UPDATE salesperson_mapping SET
                        parent_group=COALESCE(NULLIF(%s,''), parent_group),
                        party_state=COALESCE(NULLIF(%s,''), party_state),
                        party_mobile=COALESCE(NULLIF(%s,''), party_mobile),
                        credit_period_days=%s,
                        party_place=COALESCE(NULLIF(%s,''), party_place),
                        agency_name=COALESCE(NULLIF(%s,''), agency_name),
                        agent_name=COALESCE(NULLIF(%s,''), agent_name),
                        agency_mobile=COALESCE(NULLIF(%s,''), agency_mobile)
                        WHERE party_name=%s""",
                        (parent, state, mobile, credit_days, place, agency_nm, agent_nm, agency_mob, name))
                    else:
                        execute("""UPDATE salesperson_mapping SET
                        parent_group=COALESCE(NULLIF(%s,''), parent_group),
                        party_state=COALESCE(NULLIF(%s,''), party_state),
                        party_mobile=COALESCE(NULLIF(%s,''), party_mobile),
                        party_place=COALESCE(NULLIF(%s,''), party_place),
                        agency_name=COALESCE(NULLIF(%s,''), agency_name),
                        agent_name=COALESCE(NULLIF(%s,''), agent_name),
                        agency_mobile=COALESCE(NULLIF(%s,''), agency_mobile)
                        WHERE party_name=%s""",
                        (parent, state, mobile, place, agency_nm, agent_nm, agency_mob, name))
                else:
                    execute("""INSERT INTO salesperson_mapping
                        (party_name,parent_group,party_state,party_mobile,credit_period_days,party_place,agency_name,agent_name,agency_mobile)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (name, parent, state, mobile, credit_days, place or None, agency_nm or None, agent_nm or None, agency_mob or None))
            except: pass

        logger.info(f"Ledger masters synced: {len(rows)} ledgers")
        return len(rows)
    except Exception as e:
        logger.error(f"Ledger master sync error: {e}")
        return 0


# ── 4. Build Tickets from Billwise + Outstanding ──────────────
def build_tickets():
    """Build/update 1 ticket per party (UPSERT - never deletes).
    pending_amount ALWAYS = SUM(billwise.pending_amount) for that party.
    ticket_number, assigned_to, escalated, escalated_at, credit_days are
    PERMANENTLY PRESERVED across every sync - never reset."""
    logger.info("Upserting party-level tickets (preserving assignments)...")
    try:
        import pandas as pd
        execute("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='tickets_party_name_key') THEN
                    ALTER TABLE tickets ADD CONSTRAINT tickets_party_name_key UNIQUE (party_name);
                END IF;
            END $$;
        """)

        bills = query_df("""
            SELECT TRIM(REGEXP_REPLACE(party_name, '\\s+', ' ', 'g')) AS party_name,
                   COUNT(*) bill_count,
                   SUM(pending_amount) total_pending,
                   MIN(invoice_date) oldest_bill
            FROM billwise WHERE pending_amount > 0
            GROUP BY TRIM(REGEXP_REPLACE(party_name, '\\s+', ' ', 'g'))
        """)
        mapping = query_df("""SELECT TRIM(REGEXP_REPLACE(party_name, '\\s+', ' ', 'g')) AS party_name,
            agent_name, agency_name, seller_name, party_state, party_place,
            party_mobile, parent_group
            FROM salesperson_mapping""")
        mapping = mapping.drop_duplicates(subset="party_name", keep="first")

        df = bills.merge(mapping, on="party_name", how="left")
        EXCLUDE = ["bank","gst","igst","cgst","sgst","tds","profit","loss",
                   "purchase a/c","sales a/c","stock","capital","loan","cash",
                   "sundry creditor","duties","liabilit"]
        def is_debtor(row):
            g = str(row.get("parent_group","") or "").lower()
            n = str(row.get("party_name","") or "").lower()
            for kw in EXCLUDE:
                if kw in g or kw in n: return False
            return True
        df = df[df.apply(is_debtor, axis=1)]

        now = datetime.now()
        upserted = 0
        for _, p in df.iterrows():
            party = str(p.get("party_name","") or "")
            amt   = float(p.get("total_pending") or 0)
            bc    = int(p.get("bill_count") or 1)
            execute("""
                INSERT INTO tickets(bill_no,bill_date,party_name,party_gstin,
                    party_state,party_place,party_mobile,party_address,
                    agent_name,agency_name,seller_name,credit_days,
                    taxable_amount,tax_amount,total_amount,pending_amount,
                    original_amount,status,transporter,synced_at,assigned_to)
                VALUES(%s,%s,%s,'',%s,%s,%s,'',%s,%s,%s,%s,%s,0,%s,%s,%s,'Open','',%s,NULL)
                ON CONFLICT (party_name) DO UPDATE SET
                    bill_no         = EXCLUDED.bill_no,
                    bill_date       = EXCLUDED.bill_date,
                    party_state     = COALESCE(NULLIF(EXCLUDED.party_state,''),  tickets.party_state),
                    party_place     = COALESCE(NULLIF(EXCLUDED.party_place,''),  tickets.party_place),
                    party_mobile    = COALESCE(NULLIF(EXCLUDED.party_mobile,''), tickets.party_mobile),
                    agent_name      = COALESCE(NULLIF(EXCLUDED.agent_name,''),   tickets.agent_name),
                    agency_name     = COALESCE(NULLIF(EXCLUDED.agency_name,''),  tickets.agency_name),
                    seller_name     = COALESCE(NULLIF(EXCLUDED.seller_name,''),  tickets.seller_name),
                    taxable_amount  = EXCLUDED.taxable_amount,
                    total_amount    = EXCLUDED.total_amount,
                    pending_amount  = EXCLUDED.pending_amount,
                    original_amount = EXCLUDED.original_amount,
                    synced_at       = EXCLUDED.synced_at
                    -- ticket_number, assigned_to, escalated, escalated_at,
                    -- credit_days, status: NEVER touched - fully preserved
            """, (
                str(bc), str(p.get("oldest_bill","") or ""), party,
                str(p.get("party_state","") or ""), str(p.get("party_place","") or ""),
                str(p.get("party_mobile","") or ""),
                str(p.get("agent_name","") or ""), str(p.get("agency_name","") or ""),
                str(p.get("seller_name","") or ""), None,   # credit_days: filled from Tally master post-upsert (was str(bc) = bill count, a bug)
                amt, amt, amt, amt, now,
            ))
            upserted += 1

        # Close out parties with no pending bills left (keep row + history)
        execute("""
            UPDATE tickets SET pending_amount = 0
            WHERE pending_amount > 0
            AND party_name NOT IN (
                SELECT TRIM(REGEXP_REPLACE(party_name, '\\s+', ' ', 'g'))
                FROM billwise WHERE pending_amount > 0
            )
        """)

        # IMPORTANT: Do NOT derive ticket status from pending_amount.
        # Ticket lifecycle is driven by net_due (credit period + PDC + on-account).
        # Existing status/assignment/follow-up history must survive every Tally sync.

        # Assign ticket numbers ONLY to brand-new parties - never reassign existing
        maxrow = fetchone("SELECT MAX(CAST(SUBSTRING(ticket_number FROM 2) AS INT)) AS m FROM tickets WHERE ticket_number ~ '^T[0-9]+$'")
        max_num = int(maxrow["m"]) if maxrow and maxrow["m"] else 0
        new_ones = query_df("SELECT id FROM tickets WHERE ticket_number IS NULL OR ticket_number='' ORDER BY id")
        for i, row in enumerate(new_ones.itertuples(index=False), start=1):
            execute("UPDATE tickets SET ticket_number=%s WHERE id=%s", (f"T{max_num+i:03d}", row.id))

        # Fix mobile numbers
        execute("""
            UPDATE tickets t SET party_mobile = sm.party_mobile
            FROM salesperson_mapping sm
            WHERE sm.party_name = t.party_name
            AND sm.party_mobile IS NOT NULL AND LENGTH(sm.party_mobile) = 10
            AND (t.party_mobile IS NULL OR LENGTH(t.party_mobile) != 10)
        """)
        execute("""
            UPDATE tickets
            SET party_mobile = RIGHT(REGEXP_REPLACE(party_mobile, '[^0-9]', '', 'g'), 10)
            WHERE party_mobile IS NOT NULL
            AND LENGTH(REGEXP_REPLACE(party_mobile, '[^0-9]', '', 'g')) > 10
        """)

        _log_sync("tickets", upserted, "Success")
        logger.info(f"Tickets upserted: {upserted} parties (assignments preserved)")
        return upserted
    except Exception as e:
        logger.error(f"Build tickets error: {e}")
        _log_sync("tickets", 0, "Failed", str(e))
        return 0


# ── 5. Full sync ──────────────────────────────────────────────

# ── PDC: Post-Dated Cheques ─────────────────────────────────────
# Fetch instrument date (cheque date on bank allocation) + bill allocations
# (invoice numbers settled against the receipt) in addition to voucher header.
PDC_XML = """<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>PDCVouchers</ID></HEADER><BODY><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)</SVCURRENTCOMPANY>
</STATICVARIABLES>
<TDL><TDLMESSAGE>
<COLLECTION NAME="PDCVouchers" ISMODIFY="No">
<TYPE>Voucher</TYPE>
<FETCH>Date,VoucherNumber,VoucherTypeName,PartyLedgerName,Amount,
LedgerEntries.LedgerName,LedgerEntries.IsDeemedPositive,
LedgerEntries.Amount,LedgerEntries.BillAllocations.Name,
LedgerEntries.BankAllocations.PaymentFavouring,
LedgerEntries.BankAllocations.InstrumentNumber,
LedgerEntries.BankAllocations.PdcActualDate,
LedgerEntries.BankAllocations.BankName,PhoneNumber,Mobile,LedgerContactList,UDF:BMstLedAgencyNameUdf,UDF:BEIBrokerNameUdf,UDF:BGRPBrokerGroupMoUdf,UDF:BMstLedPlaceUdf</FETCH>
<FILTER>F1</FILTER>
</COLLECTION>
<SYSTEM TYPE="Formulae" NAME="F1">$VoucherTypeName = "Post Dated Receipt"</SYSTEM>
</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>
"""

def _parse_tally_date(raw):
    """Parse Tally YYYYMMDD (or dated string) → date | None."""
    from datetime import datetime as _dt
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%d", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return _dt.strptime(raw[:10] if fmt != "%Y%m%d" else raw[:8], fmt).date()
        except Exception:
            continue
    return None

def _pdc_instrument_from_voucher(v):
    """Pull cheque/instrument fields from BANKALLOCATIONS (confirmed from sample XML).

    Tags: INSTRUMENTDATE, INSTRUMENTNUMBER, PDCACTUALDATE, BANKERSDATE, BANKNAME
    Cheque date used in app = INSTRUMENTDATE (user choice).
    """
    inst_date = None
    pdc_actual = None
    bankers = None
    inst_no = ""
    bank_name = ""
    for bank in v.findall(".//BANKALLOCATIONS.LIST"):
        if not list(bank):
            continue
        d = _parse_tally_date(bank.findtext("INSTRUMENTDATE", "") or "")
        if d and (inst_date is None or d > inst_date):
            inst_date = d
        pa = _parse_tally_date(bank.findtext("PDCACTUALDATE", "") or "")
        if pa and (pdc_actual is None or pa > pdc_actual):
            pdc_actual = pa
        bd = _parse_tally_date(bank.findtext("BANKERSDATE", "") or "")
        if bd and (bankers is None or bd > bankers):
            bankers = bd
        no = (bank.findtext("INSTRUMENTNUMBER", "") or "").strip()
        if no and not inst_no:
            inst_no = no
        bn = (bank.findtext("BANKNAME", "") or "").strip()
        if bn and not bank_name:
            bank_name = bn
    return inst_date, inst_no, pdc_actual, bankers, bank_name


def _pdc_bills_from_voucher(v):
    """Settled invoice numbers from BILLALLOCATIONS.

    Confirmed from sample XML: invoice number is <NAME> (e.g. 3198, 3805),
    not BILLNAME. BILLTYPE is typically 'Agst Ref'.
    """
    bills = []
    seen = set()
    skip = {"ON ACCOUNT", "(ON ACCOUNT)", "NEW REF", "AGST REF"}
    for bill in v.findall(".//BILLALLOCATIONS.LIST"):
        if not list(bill):
            continue
        # Prefer <NAME> — confirmed tag for invoice number
        name = (bill.findtext("NAME", "") or bill.findtext("BILLNAME", "") or "").strip()
        if not name or name.upper() in skip:
            continue
        key = name.upper()
        if key in seen:
            continue
        seen.add(key)
        bills.append(name)
    refs = ", ".join(bills)
    return refs, refs


def _pdc_amount_from_voucher(v):
    """Amount from party ledger line that has bill allocations (confirmed)."""
    for led in v.findall(".//ALLLEDGERENTRIES.LIST"):
        has_bills = any(list(b) for b in led.findall("BILLALLOCATIONS.LIST"))
        has_bank = any(list(b) for b in led.findall("BANKALLOCATIONS.LIST"))
        if has_bills and not has_bank:
            try:
                a = abs(float((led.findtext("AMOUNT", "0") or "0").strip() or 0))
                if a:
                    return a
            except Exception:
                pass
    for bank in v.findall(".//BANKALLOCATIONS.LIST"):
        if not list(bank):
            continue
        try:
            a = abs(float((bank.findtext("AMOUNT", "0") or "0").strip() or 0))
            if a:
                return a
        except Exception:
            pass
    try:
        return abs(float((v.findtext("AMOUNT", "0") or "0").strip() or 0))
    except Exception:
        return 0.0


def sync_pdc():
    import xml.etree.ElementTree as _ET
    logger.info("Syncing PDC (post-dated cheques)...")
    try:
        execute("""CREATE TABLE IF NOT EXISTS pdc_entries (
            id SERIAL PRIMARY KEY,
            party_name TEXT,
            voucher_number TEXT,
            cheque_date DATE,
            amount NUMERIC,
            narration TEXT,
            voucher_type TEXT,
            synced_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(voucher_number, party_name)
        )""")
        for ddl in (
            "ALTER TABLE pdc_entries ADD COLUMN IF NOT EXISTS voucher_date DATE",
            "ALTER TABLE pdc_entries ADD COLUMN IF NOT EXISTS instrument_date DATE",
            "ALTER TABLE pdc_entries ADD COLUMN IF NOT EXISTS pdc_actual_date DATE",
            "ALTER TABLE pdc_entries ADD COLUMN IF NOT EXISTS instrument_number TEXT",
            "ALTER TABLE pdc_entries ADD COLUMN IF NOT EXISTS bill_refs TEXT",
        ):
            try:
                execute(ddl)
            except Exception:
                pass

        xml_text = _post_xml(PDC_XML).replace("UDF:", "UDF_")
        # Strip Tally control entities like &#4; (same as probe)
        xml_text = re.sub(r"&#0*([0-8]|1[0-9]|2[0-9]|3[01]);", "", xml_text)
        root = _ET.fromstring(xml_text)

        all_vouchers = root.findall(".//VOUCHER")
        valid_vouchers = [v for v in all_vouchers if (v.findtext("PARTYLEDGERNAME","") or "").strip()]
        logger.info(f"PDC fetch: {len(all_vouchers)} total, {len(valid_vouchers)} with party name")
        if len(valid_vouchers) < 50:
            logger.warning(f"PDC WARNING: Only {len(valid_vouchers)} entries from Tally - may be incomplete! Expected 85+")

        rows = []
        for v in root.findall(".//VOUCHER"):
            try:
                vno          = (v.findtext("VOUCHERNUMBER","") or "").strip()
                vtype        = (v.findtext("VOUCHERTYPENAME","") or "").strip()
                voucher_date = _parse_tally_date(v.findtext("DATE",""))

                # Party name from FIRSTCRLED (debit party = cheque issuer)
                party = (v.findtext("FIRSTCRLED","") or
                         v.findtext("PARTYLEDGERNAME","") or "").strip()

                _bnames    = []
                narr       = (v.findtext("NARRATION","") or "").strip()
                inst_date  = None
                pdc_actual = None
                _cheque_no = ""
                _bank_name = (v.findtext("FIRSTDRLED","") or "").strip()
                amt_party  = 0

                # Parse LEDGERENTRIES.LIST - party entry has ISDEEMEDPOSITIVE=No
                for led in v.findall("LEDGERENTRIES.LIST"):
                    is_pos  = (led.findtext("ISDEEMEDPOSITIVE","") or "").strip().lower()
                    ledname = (led.findtext("LEDGERNAME","") or "").strip()
                    a       = abs(float(led.findtext("AMOUNT","0") or 0))
                    if is_pos == "no" and ledname and not party:
                        party = ledname
                    # Bill allocations
                    for ba in led.findall("BILLALLOCATIONS.LIST"):
                        bn = (ba.findtext("NAME","") or "").strip()
                        if bn: _bnames.append(bn)
                    # Bank allocations
                    for bk in led.findall("BANKALLOCATIONS.LIST"):
                        pdc_raw = (bk.findtext("PDCACTUALDATE","") or
                                   bk.findtext("INSTRUMENTDATE","") or "").strip()
                        if pdc_raw and len(pdc_raw)==8:
                            inst_date  = f"{pdc_raw[:4]}-{pdc_raw[4:6]}-{pdc_raw[6:8]}"
                            pdc_actual = inst_date
                        _cheque_no = (bk.findtext("INSTRUMENTNUMBER","") or _cheque_no).strip()
                        _bank_name = (bk.findtext("BANKNAME","") or _bank_name).strip()

                if _bnames: narr = ", ".join(_bnames)
                party = re.sub(r"\s+", " ", party).strip()

                if not party or not voucher_date:
                    continue

                amt = _pdc_amount_from_voucher(v)
                # Skip _pdc_instrument_from_voucher - it uses BANKALLOCATIONS.LIST (dots)
                # which Tally API doesn't return. Values already parsed above from LEDGERENTRIES.LIST
                inst_no = _cheque_no
                if not _bank_name:
                    _bank_name = ""
                bill_refs = narr
                bill_refs, _ = _pdc_bills_from_voucher(v)

                # User choice: cheque_date = INSTRUMENTDATE, fallback voucher DATE
                # Use inst_date only if it's AFTER voucher_date (true PDC date)
                # If inst_date is before or equal to voucher_date, use voucher_date
                if inst_date:
                    try:
                        from datetime import date as _d
                        _inst = _d.fromisoformat(str(inst_date))
                        _vdt  = _d.fromisoformat(str(voucher_date))
                        cheque_date = str(inst_date) if _inst >= _vdt else str(voucher_date)
                    except Exception:
                        cheque_date = str(inst_date) if inst_date else str(voucher_date)
                else:
                    cheque_date = str(voucher_date)
                rows.append((
                    party, vno, cheque_date, amt, narr, vtype,
                    voucher_date, inst_date, pdc_actual, inst_no or None, bill_refs or None,
                ))
            except Exception:
                pass

        # Smart delete: remove DB entries no longer in Tally
        # Safety: only runs if Tally returned >10 entries (confirms Tally is online)
        # NO DELETE - only upsert from Tally

        for (party, vno, cheque_date, amt, narr, vtype,
             voucher_date, inst_date, pdc_actual, inst_no, bill_refs) in rows:
            try:
                execute("""INSERT INTO pdc_entries
                    (party_name, voucher_number, cheque_date, amount, narration, voucher_type,
                     voucher_date, instrument_date, pdc_actual_date, instrument_number, bill_refs)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (voucher_number, party_name) DO UPDATE SET
                        cheque_date=EXCLUDED.cheque_date,
                        amount=EXCLUDED.amount,
                        narration=EXCLUDED.narration,
                        voucher_date=EXCLUDED.voucher_date,
                        instrument_date=EXCLUDED.instrument_date,
                        pdc_actual_date=EXCLUDED.pdc_actual_date,
                        instrument_number=EXCLUDED.instrument_number,
                        bill_refs=EXCLUDED.bill_refs,
                        synced_at=NOW()""",
                    (party, vno, cheque_date, amt, narr, vtype,
                     voucher_date, inst_date, pdc_actual, inst_no, bill_refs))
            except Exception:
                pass
        try:
            execute(r"""
                UPDATE pdc_entries p
                SET party_name = t.party_name
                FROM tickets t
                WHERE regexp_replace(upper(p.party_name),'\\s+',' ','g')
                    = regexp_replace(upper(t.party_name),'\\s+',' ','g')
                  AND p.party_name IS DISTINCT FROM t.party_name
            """)
        except Exception as e:
            logger.error(f"PDC party-name align error: {e}")

        with_inst = sum(1 for r in rows if r[7] is not None)
        with_bills = sum(1 for r in rows if r[10])
        logger.info(f"PDC synced: {len(rows)} entries | instrument_date={with_inst} | with bills={with_bills}")
        return len(rows)
    except Exception as e:
        logger.error(f"PDC sync error: {e}")
        return 0

def sync_credit_days_from_master():
    """Copy Tally credit period onto tickets.

    Primary source is salesperson_mapping.credit_period_days (filled from
    BILLCREDITPERIOD during sync_ledger_masters). Fallback to
    tally_party_master.credit_period_days when present.
    """
    # Prefer salesperson_mapping (always updated from Tally BILLCREDITPERIOD)
    execute(r"""
        UPDATE tickets t
        SET credit_days = sm.credit_period_days
        FROM salesperson_mapping sm
        WHERE regexp_replace(upper(sm.party_name),'\\s+',' ','g')
            = regexp_replace(upper(t.party_name),'\\s+',' ','g')
          AND sm.credit_period_days IS NOT NULL
          AND sm.credit_period_days > 0
          AND t.credit_days IS DISTINCT FROM sm.credit_period_days::text
    """)
    # Fallback: tally_party_master if column exists and mapping was empty
    try:
        execute(r"""
            UPDATE tickets t
            SET credit_days = tpm.credit_period_days
            FROM tally_party_master tpm
            WHERE regexp_replace(upper(tpm.party_name),'\\s+',' ','g')
                = regexp_replace(upper(t.party_name),'\\s+',' ','g')
              AND tpm.credit_period_days IS NOT NULL
              AND tpm.credit_period_days > 0
              AND (t.credit_days IS NULL OR t.credit_days = 0)
        """)
    except Exception:
        pass


def recompute_net_due(default_credit_days=30):
    """Calculate Net Due from overdue billwise amounts, less PDC and on-account."""
    sql = r"""
        WITH due AS (
            SELECT
                t.id,
                GREATEST(
                    COALESCE((
                        SELECT SUM(b.pending_amount)
                        FROM billwise b
                        WHERE regexp_replace(upper(b.party_name),'\s+',' ','g')
                            = regexp_replace(upper(t.party_name),'\s+',' ','g')
                          AND b.pending_amount > 0
                          AND b.invoice_no NOT ILIKE '%%on account%%'
                          AND b.invoice_date ~ '^[0-9]{2}-[A-Za-z]{3}-[0-9]{2}$'
                          AND (
                                TO_DATE(b.invoice_date,'DD-Mon-YY')
                                + (COALESCE(NULLIF(t.credit_days,'')::int,%s) || ' days')::interval
                              ) < CURRENT_DATE
                    ),0)
                    - COALESCE((
                        SELECT SUM(pe.amount)
                        FROM pdc_entries pe
                        WHERE regexp_replace(upper(pe.party_name),'\s+',' ','g')
                            = regexp_replace(upper(t.party_name),'\s+',' ','g')
                    ),0)
                    - COALESCE((
                        SELECT SUM(b2.pending_amount)
                        FROM billwise b2
                        WHERE regexp_replace(upper(b2.party_name),'\s+',' ','g')
                            = regexp_replace(upper(t.party_name),'\s+',' ','g')
                          AND b2.pending_amount > 0
                          AND b2.invoice_no ILIKE '%%on account%%'
                    ),0),
                    0
                ) AS net_due
            FROM tickets t
        )
        UPDATE tickets t
        SET net_due = due.net_due
        FROM due
        WHERE t.id = due.id
    """
    execute(sql, (default_credit_days,))



def apply_ticket_due_cycle():
    """Apply ticket visibility/assignment rules from the NEW net_due state.

    - net_due <= 0: close the ticket, but preserve assigned_to and all history.
    - net_due > 0 after a previously closed cycle: start a fresh collection
      cycle by clearing assignment and archiving OLD followups only.
    - net_due > 0 for an already-open ticket: preserve current assignment and
      followups.
    - No followup rows are deleted.
    """
    try:
        execute("ALTER TABLE followups ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE")
    except Exception as e:
        logger.warning(f"Could not ensure followups.archived: {e}")

    # A closed ticket with a new positive Net Due is a genuinely new cycle.
    # Archive its old followups and unassign it so the owner can reassign it.
    execute("""
        UPDATE followups f
        SET archived = TRUE
        FROM tickets t
        WHERE f.party_name = t.party_name
          AND COALESCE(t.net_due,0) > 0
          AND COALESCE(t.status,'') = 'Closed'
          AND (f.archived IS NULL OR f.archived = FALSE)
    """)

    execute("""
        UPDATE tickets
        SET assigned_to = NULL,
            assigned_on = NULL,
            status = 'Open',
            closed_date = NULL
        WHERE COALESCE(net_due,0) > 0
          AND COALESCE(status,'') = 'Closed'
    """)

    # Closing does NOT clear assignment/history.
    execute("""
        UPDATE tickets
        SET status = 'Closed',
            closed_date = COALESCE(closed_date, CURRENT_DATE)
        WHERE COALESCE(net_due,0) <= 0
          AND COALESCE(status,'') <> 'Closed'
    """)

    execute("""
        UPDATE tickets
        SET status = 'Open'
        WHERE COALESCE(net_due,0) > 0
    """)

    logger.info("Ticket due-cycle state applied: net_due controls Open/Closed; "
                "new cycles are unassigned and old followups archived.")


def run_full_sync():
    if not tally_alive():
        try:
            _log_sync("full_sync", 0, "Skipped", "Tally not reachable")
        except Exception:
            pass
        print("Tally not reachable - FULL SYNC ABORTED, existing data kept")
        return {"status": "skipped", "reason": "Tally not reachable"}
    logger.info("="*50)
    logger.info(f"TALLY URL: {TALLY_URL}")
    logger.info("FULL TALLY SYNC STARTED")
    logger.info("="*50)
    results = {}
    try: results["outstanding"] = sync_outstanding()
    except Exception as e: results["outstanding"] = f"ERROR: {e}"
    try: results["billwise"] = sync_billwise()
    except Exception as e: results["billwise"] = f"ERROR: {e}"
    try: results["ledger_masters"] = sync_ledger_masters()
    except Exception as e: results["ledger_masters"] = f"ERROR: {e}"
    try: results["tickets"] = build_tickets()
    except Exception as e: results["tickets"] = f"ERROR: {e}"
    try: results["pdc"] = sync_pdc()
    except Exception as e: results["pdc"] = f"ERROR: {e}"
	# Fix single-digit dates after every sync
    try:
        from db import execute
        execute("""UPDATE billwise SET invoice_date = LPAD(SPLIT_PART(invoice_date,'-',1),2,'0') || '-' || SPLIT_PART(invoice_date,'-',2) || '-' || SPLIT_PART(invoice_date,'-',3) WHERE invoice_date ~ '^[0-9]{1}-[A-Za-z]'""")
    except: pass
# Fix mobile numbers after every sync
    try:
        execute("""UPDATE salesperson_mapping 
            SET party_mobile = RIGHT(REGEXP_REPLACE(party_mobile, '[^0-9]', '', 'g'), 10)
            WHERE party_mobile IS NOT NULL 
            AND LENGTH(REGEXP_REPLACE(party_mobile, '[^0-9]', '', 'g')) >= 10""")
        execute("""UPDATE tickets t SET party_mobile = sm.party_mobile
            FROM salesperson_mapping sm
            WHERE sm.party_name = t.party_name
            AND sm.party_mobile IS NOT NULL
            AND LENGTH(sm.party_mobile) = 10""")
        # Sync party_place (city) and agency_mobile to tickets table
        execute("""
            UPDATE tickets t SET
                party_place = sm.party_place,
                agency_mobile = sm.agency_mobile
            FROM salesperson_mapping sm
            WHERE t.party_name = sm.party_name
            AND (sm.party_place IS NOT NULL OR sm.agency_mobile IS NOT NULL)
        """)
        # Also update party_mobile from tally_party_master (newer source)
        _c2 = None
        try:
            from db import get_conn as _gc2, release_conn as _rc2
            _c2 = _gc2()
            _cu2 = _c2.cursor()
            _cu2.execute("""
                UPDATE tickets t SET party_mobile = tpm.mobile
                FROM tally_party_master tpm
                WHERE tpm.party_name = t.party_name
                AND tpm.mobile IS NOT NULL AND TRIM(tpm.mobile) != ''
                AND tpm.mobile != t.party_mobile
            """)
            _cu2.execute("""
                UPDATE salesperson_mapping sm SET party_mobile = tpm.mobile
                FROM tally_party_master tpm
                WHERE tpm.party_name = sm.party_name
                AND tpm.mobile IS NOT NULL AND TRIM(tpm.mobile) != ''
                AND tpm.mobile != sm.party_mobile
            """)
            _c2.commit()
            _cu2.close()
            _rc2(_c2)
        except Exception as _me:
            logger.error(f"Mobile update from tpm: {_me}")
            if _c2:
                try: _rc2(_c2)
                except: pass
        logger.info("Mobile numbers synced to tickets")
    except Exception as e:
        logger.error(f"Mobile sync error: {e}")

    # Credit period + net_due — MUST run last, after build_tickets/ledger_masters/pdc
    try:
        sync_credit_days_from_master()
        recompute_net_due()
        apply_ticket_due_cycle()
        results["credit_netdue"] = "recomputed"
        logger.info("Credit days pulled from master + net_due + ticket cycle state recomputed")
    except Exception as e:
        results["credit_netdue"] = f"ERROR: {e}"
        logger.warning(f"Credit/net_due recompute skipped (will retry in post-sync): {e}")
        # _post_sync_updates() handles this as fallback

    logger.info(f"SYNC COMPLETE: {results}")
    _post_sync_updates()
    return results

if __name__ == "__main__":
    run_full_sync()


def _post_sync_updates():
    """
    Runs after every sync.
    Uses pool properly with try/finally to always release connection.
    1. Sync credit_days from salesperson_mapping
    2. Clear nan + sync agency from tally_party_master
    3. Expand short agency names
    4. Auto-archive followups for net_due=0 parties
    Note: net_due already recalculated by recompute_net_due() in run_full_sync
    """
    import logging as _log2
    _logger = _log2.getLogger(__name__)
    from db import get_conn as _gc, release_conn as _rc
    _c = None
    try:
        _c = _gc()
        _cu = _c.cursor()

        # 1. Sync credit_days from salesperson_mapping
        _cu.execute("""
            UPDATE tickets t SET credit_days = sm.credit_period_days::text
            FROM salesperson_mapping sm
            WHERE sm.party_name = t.party_name
            AND sm.credit_period_days IS NOT NULL AND sm.credit_period_days > 0
        """)
        _logger.info(f"Post-sync: credit_days={_cu.rowcount} parties")

        # 2. Clear nan agency
        _cu.execute("""UPDATE tickets SET agency_name = NULL
                       WHERE LOWER(TRIM(COALESCE(agency_name,'')))
                       IN ('nan','none','null','','—')""")

        # 3a. Sync agency from salesperson_mapping (preserves manual overrides)
        _cu.execute("""
            UPDATE tickets t SET agency_name = sm.agency_name
            FROM salesperson_mapping sm
            WHERE sm.party_name = t.party_name
            AND sm.agency_name IS NOT NULL AND TRIM(sm.agency_name) != ''
            AND LOWER(TRIM(sm.agency_name)) NOT IN ('nan','none','null')
            AND (t.agency_name IS NULL OR TRIM(t.agency_name) = '')
        """)
        _logger.info(f"Post-sync: agency from mapping={_cu.rowcount} parties")

        # 3b. Sync agency from tally_party_master (only if longer or empty)
        _cu.execute("""
            UPDATE tickets t SET agency_name = tpm.agency_name
            FROM tally_party_master tpm
            WHERE UPPER(TRIM(tpm.party_name)) = UPPER(TRIM(t.party_name))
            AND tpm.agency_name IS NOT NULL AND TRIM(tpm.agency_name) != ''
            AND LOWER(TRIM(tpm.agency_name)) NOT IN ('nan','none','null')
            AND (t.agency_name IS NULL OR TRIM(t.agency_name) = ''
                 OR LENGTH(tpm.agency_name) > LENGTH(t.agency_name))
        """)
        _logger.info(f"Post-sync: agency from tpm={_cu.rowcount} parties")

        # 3c. Expand truncated agency names using LIKE (fixes Tally truncation bug)
        _cu.execute(r"""
            UPDATE tickets t SET agency_name = tam.agency_name
            FROM tally_agency_master tam
            WHERE tam.agency_name LIKE t.agency_name || '%%'
            AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
            AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
            AND LOWER(t.agency_name) NOT IN ('nan','none','null','self','cash')
        """)
        _cu.execute(r"""
            UPDATE tally_party_master tpm SET agency_name = tam.agency_name
            FROM tally_agency_master tam
            WHERE tam.agency_name LIKE tpm.agency_name || '%%'
            AND LENGTH(tam.agency_name) > LENGTH(COALESCE(tpm.agency_name,''))
            AND tpm.agency_name IS NOT NULL AND TRIM(tpm.agency_name) != ''
            AND LOWER(tpm.agency_name) NOT IN ('nan','none','null','self','cash')
        """)
        _logger.info(f"Post-sync: truncated agencies expanded")

        # 3c. Expand truncated agency names using LIKE (fixes Tally truncation bug)
        _cu.execute(r"""
            UPDATE tickets t SET agency_name = tam.agency_name
            FROM tally_agency_master tam
            WHERE tam.agency_name LIKE t.agency_name || '%%'
            AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
            AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
            AND LOWER(t.agency_name) NOT IN ('nan','none','null','self','cash')
        """)
        _cu.execute(r"""
            UPDATE tally_party_master tpm SET agency_name = tam.agency_name
            FROM tally_agency_master tam
            WHERE tam.agency_name LIKE tpm.agency_name || '%%'
            AND LENGTH(tam.agency_name) > LENGTH(COALESCE(tpm.agency_name,''))
            AND tpm.agency_name IS NOT NULL AND TRIM(tpm.agency_name) != ''
            AND LOWER(tpm.agency_name) NOT IN ('nan','none','null','self','cash')
        """)
        _logger.info(f"Post-sync: truncated agencies expanded")

        # 4. Expand short agency names to full (only non-empty agencies)
        _cu.execute("""
            UPDATE tickets t SET agency_name = tam.agency_name
            FROM tally_agency_master tam
            WHERE regexp_replace(UPPER(tam.agency_name),'\\s+',' ','g')
                LIKE regexp_replace(UPPER(t.agency_name),'\\s+',' ','g') || '%%'
            AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
            AND t.agency_name IS NOT NULL AND TRIM(t.agency_name) != ''
            AND LOWER(TRIM(t.agency_name)) NOT IN ('nan','none','null','self','cash')
        """)
        _logger.info(f"Post-sync: agency expanded={_cu.rowcount}")

        # 4b. Also expand in tally_party_master
        _cu.execute("""
            UPDATE tally_party_master tpm SET agency_name = tam.agency_name
            FROM tally_agency_master tam
            WHERE regexp_replace(UPPER(tam.agency_name),'\\s+',' ','g')
                LIKE regexp_replace(UPPER(tpm.agency_name),'\\s+',' ','g') || '%%'
            AND LENGTH(tam.agency_name) > LENGTH(COALESCE(tpm.agency_name,''))
            AND tpm.agency_name IS NOT NULL AND TRIM(tpm.agency_name) != ''
            AND LOWER(TRIM(tpm.agency_name)) NOT IN ('nan','none','null','self','cash')
        """)
        _logger.info(f"Post-sync: tpm agency expanded={_cu.rowcount}")

        # 4c. Clear only NULL/nan/none agency names (keep self-referencing - valid in Tally)
        _cu.execute("""UPDATE tickets SET agency_name=NULL
                        WHERE LOWER(TRIM(COALESCE(agency_name,''))) IN ('nan','none','null','')""")
        _cu.execute("""UPDATE tally_party_master SET agency_name=NULL
                        WHERE LOWER(TRIM(COALESCE(agency_name,''))) IN ('nan','none','null','')""")
        _cu.execute("""UPDATE tickets SET agency_name=NULL
                        WHERE UPPER(TRIM(agency_name))=UPPER(TRIM(party_name))""")
        _cu.execute("""UPDATE tally_party_master SET agency_name=NULL
                        WHERE UPPER(TRIM(agency_name))=UPPER(TRIM(party_name))""")

        # 4d. Apply manual agency overrides (always wins over Tally)
        _cu.execute("""
            UPDATE tickets t SET agency_name = mo.agency_name
            FROM manual_agency_override mo
            WHERE t.party_name = mo.party_name
            AND t.agency_name IS DISTINCT FROM mo.agency_name
        """)
        if _cu.rowcount > 0:
            _logger.info(f"Post-sync: manual agency overrides applied={_cu.rowcount}")

        # Follow-up lifecycle is handled by apply_ticket_due_cycle().
        # Do NOT mass archive/unarchive here: old follow-up history must remain
        # untouched unless a ticket actually starts a new due cycle.

        _c.commit()
        _cu.close()
        _logger.info("Post-sync updates complete")

    except Exception as _e:
        _logger.warning(f"Post-sync update error: {_e}")
        import traceback as _tb
        _logger.warning(_tb.format_exc())
        if _c:
            try: _c.rollback()
            except: pass
    finally:
        if _c:
            try: _rc(_c)
            except: pass

