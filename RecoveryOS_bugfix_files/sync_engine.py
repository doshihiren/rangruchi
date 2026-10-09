# ============================================================
# sync_engine.py  –  Tally → PostgreSQL sync engine
# ============================================================
import requests
import xml.etree.ElementTree as ET
import logging
import re
from datetime import datetime
from config import TALLY_URL
from db import execute, executemany, fetchone, query_df

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
<TYPE>Ledger</TYPE><FETCH>Name,ClosingBalance,Parent</FETCH>
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
            except: pass
        execute("DELETE FROM outstanding")
        executemany("INSERT INTO outstanding(party_name,balance,synced_at) VALUES(%s,%s,%s)", rows)
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
<FETCH>Name, BillAllocations.List</FETCH>
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
                        party_name = re.sub(r'\(RR\d+\)\s*$', '', re.sub(r'\s+', ' ', party_name).strip()).strip()

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

        execute("DELETE FROM billwise")
        executemany("""INSERT INTO billwise(party_name,invoice_date,invoice_no,overdue_days,pending_amount,synced_at)
                       VALUES(%s,%s,%s,%s,%s,%s)""", rows)

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
<FETCH>Name,Parent,LedstateName,PartyGstin,LedgerMobile,Address,Pincode,BillCreditPeriod</FETCH>
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
                mobile  = led.findtext("LEDGERMOBILE","").strip()
                addr_el = led.findtext("ADDRESS","")
                addr    = addr_el.strip() if addr_el else ""
                pin     = led.findtext("PINCODE","").strip()

                place      = led.findtext("UDF_BMSTLEDPLACEUDF","").strip()
                agency_nm  = led.findtext("UDF_BMSTLEDAGENCYNAMEUDF","").strip()
                agent_nm   = led.findtext("UDF_BEIBROKERNAMEUDF","").strip()
                agency_mob = led.findtext("UDF_BGRPBROKERGROUPMOUDF","").strip()
                try:
                    cp_raw = led.findtext("BILLCREDITPERIOD","").strip()
                    # Tally returns "60 Days", "30 Days" etc - extract number
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

        # Recompute status for ALL tickets
        execute("""
            UPDATE tickets SET
                status = CASE
                    WHEN pending_amount <= 0 THEN 'Closed'
                    WHEN pending_amount < original_amount THEN 'Partial'
                    ELSE 'Open'
                END,
                closed_date = CASE
                    WHEN pending_amount <= 0 AND closed_date IS NULL THEN CURRENT_DATE
                    WHEN pending_amount > 0 THEN NULL
                    ELSE closed_date
                END
        """)

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
<COLLECTION NAME="PDCVouchers" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
<TYPE>Voucher</TYPE>
<FETCH>Date,VoucherNumber,VoucherTypeName,PartyLedgerName,Amount,Narration,IsPostDated,AllLedgerEntries.*,LedgerEntries.*,BankAllocations.*,BillAllocations.*</FETCH>
<FILTER>PostDatedFilter</FILTER>
</COLLECTION>
<SYSTEM TYPE="Formulae" NAME="PostDatedFilter">$IsPostDated = Yes</SYSTEM>
</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""

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

        rows = []
        for v in root.findall(".//VOUCHER"):
            try:
                party = (v.findtext("PARTYLEDGERNAME", "") or "").strip()
                if not party:
                    for led in v.findall(".//ALLLEDGERENTRIES.LIST"):
                        nm = (led.findtext("LEDGERNAME", "") or "").strip()
                        has_bills = any(list(b) for b in led.findall("BILLALLOCATIONS.LIST"))
                        if has_bills and nm:
                            party = nm
                            break
                party = re.sub(r"\s+", " ", party).strip()
                vno = (v.findtext("VOUCHERNUMBER", "") or "").strip()
                vtype = (v.findtext("VOUCHERTYPENAME", "") or "").strip()
                narr = (v.findtext("NARRATION", "") or "").strip()
                voucher_date = _parse_tally_date(v.findtext("DATE", ""))
                if not party or not voucher_date:
                    continue

                amt = _pdc_amount_from_voucher(v)
                inst_date, inst_no, pdc_actual, _bankers, _bank = _pdc_instrument_from_voucher(v)
                bill_refs, _ = _pdc_bills_from_voucher(v)

                # User choice: cheque_date = INSTRUMENTDATE, fallback voucher DATE
                cheque_date = inst_date or voucher_date
                rows.append((
                    party, vno, cheque_date, amt, narr, vtype,
                    voucher_date, inst_date, pdc_actual, inst_no or None, bill_refs or None,
                ))
            except Exception:
                pass

        execute("DELETE FROM pdc_entries")
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
                WHERE regexp_replace(upper(p.party_name),'\s+',' ','g')
                    = regexp_replace(upper(t.party_name),'\s+',' ','g')
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
        WHERE regexp_replace(upper(sm.party_name),'\s+',' ','g')
            = regexp_replace(upper(t.party_name),'\s+',' ','g')
          AND sm.credit_period_days IS NOT NULL
          AND sm.credit_period_days > 0
          AND t.credit_days IS DISTINCT FROM sm.credit_period_days
    """)
    # Fallback: tally_party_master if column exists and mapping was empty
    try:
        execute(r"""
            UPDATE tickets t
            SET credit_days = tpm.credit_period_days
            FROM tally_party_master tpm
            WHERE regexp_replace(upper(tpm.party_name),'\s+',' ','g')
                = regexp_replace(upper(t.party_name),'\s+',' ','g')
              AND tpm.credit_period_days IS NOT NULL
              AND tpm.credit_period_days > 0
              AND (t.credit_days IS NULL OR t.credit_days = 0)
        """)
    except Exception:
        pass


def recompute_net_due(default_credit_days=30):
    """net_due = overdue amount (bills past each party's Tally credit period)
    - PDC - on-account unallocated, floored at 0.

    PDC is joined on normalized party names so spacing/case mismatches
    (e.g. TXTILE vs TEXTILE spelling aside, extra spaces) still subtract.
    """
    execute(rf"""
        UPDATE tickets t
        SET net_due = GREATEST(s.overdue - s.pdc - s.unalloc, 0)
        FROM (
            SELECT tk.id,
                   COALESCE(od.amt,0) AS overdue,
                   COALESCE(pd.amt,0) AS pdc,
                   COALESCE(ua.amt,0) AS unalloc
            FROM tickets tk
            LEFT JOIN LATERAL (
                SELECT SUM(b.pending_amount) AS amt
                FROM billwise b
                WHERE regexp_replace(upper(b.party_name),'\s+',' ','g')
                    = regexp_replace(upper(tk.party_name),'\s+',' ','g')
                  AND b.pending_amount > 0
                  AND b.invoice_no NOT ILIKE '%on account%'
                  AND b.invoice_date ~ '^[0-9]{{2}}-[A-Za-z]{{3}}-[0-9]{{2}}$'
                  AND (TO_DATE(b.invoice_date,'DD-Mon-YY')
                       + (COALESCE(NULLIF(tk.credit_days,0),{default_credit_days})||' days')::interval) < CURRENT_DATE
            ) od ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(pe.amount) AS amt FROM pdc_entries pe
                WHERE regexp_replace(upper(pe.party_name),'\s+',' ','g')
                    = regexp_replace(upper(tk.party_name),'\s+',' ','g')
            ) pd ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(b.pending_amount) AS amt
                FROM billwise b
                WHERE regexp_replace(upper(b.party_name),'\s+',' ','g')
                    = regexp_replace(upper(tk.party_name),'\s+',' ','g')
                  AND b.pending_amount > 0
                  AND b.invoice_no ILIKE '%on account%'
            ) ua ON TRUE
        ) s
        WHERE t.id = s.id
    """)
    # Hide cleared parties from Follow-ups automatically
    try:
        execute("""
            ALTER TABLE followups ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE
        """)
        execute("""
            UPDATE followups f SET archived = TRUE
            FROM tickets t
            WHERE f.party_name = t.party_name
              AND COALESCE(t.net_due, 0) = 0
              AND (f.archived IS NULL OR f.archived = FALSE)
        """)
        # Un-archive if net_due becomes positive again
        execute("""
            UPDATE followups f SET archived = FALSE
            FROM tickets t
            WHERE f.party_name = t.party_name
              AND COALESCE(t.net_due, 0) > 0
              AND f.archived = TRUE
        """)
    except Exception as e:
        logger.error(f"Followup archive after net_due: {e}")


def run_full_sync():
    logger.info("="*50)
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
        logger.info("Mobile numbers synced to tickets")
    except Exception as e:
        logger.error(f"Mobile sync error: {e}")

    # Credit period + net_due — MUST run last, after build_tickets/ledger_masters/pdc
    try:
        sync_credit_days_from_master()
        recompute_net_due()
        results["credit_netdue"] = "recomputed"
        logger.info("Credit days pulled from master + net_due recomputed")
    except Exception as e:
        results["credit_netdue"] = f"ERROR: {e}"
        logger.error(f"Credit/net_due recompute error: {e}")

    logger.info(f"SYNC COMPLETE: {results}")
    return results

if __name__ == "__main__":
    run_full_sync()
