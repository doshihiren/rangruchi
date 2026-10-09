"""
probe_pdc_xml.py  -- TEMP diagnostic (CMD display only)
Parses your sample Tally receipt XML and prints instrument date + settled invoices.

Usage:
  python probe_pdc_xml.py
  python probe_pdc_xml.py "C:\\Projects\\tally_project\\Receipt_160-25-26.xml"
"""
from __future__ import annotations
import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

DEFAULT_FILES = [
    r"C:\Projects\tally_project\Receipt_160-25-26.xml",
    r"C:\Projects\tally_project\Receipt_965.xml",
]
SKIP_BILL_NAMES = {"ON ACCOUNT", "(ON ACCOUNT)", "NEW REF", "AGST REF"}


def clean_tally_xml(text: str) -> str:
    text = text.replace("UDF:", "UDF_")
    # Strip ALL control-character numeric entities (&#0;..&#31; except 9/10/13)
    # Tally uses &#4; heavily ("Not Applicable")
    text = re.sub(r"&#0*([0-8]|1[0-9]|2[0-9]|3[01]);", "", text)
    text = re.sub(r"&#x0*([0-8BbCcEeFf]|1[0-9A-Fa-f]);", "", text)
    # Absolute fallback: remove any remaining &#N; under 32
    def drop_ctrl(m):
        try:
            n = int(m.group(1))
            return "" if n < 32 and n not in (9, 10, 13) else m.group(0)
        except Exception:
            return ""
    text = re.sub(r"&#(\d+);", drop_ctrl, text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    return text


def fmt_date(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "-"
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").strftime("%d-%b-%Y")
    except Exception:
        return raw


def money(raw: str) -> float:
    try:
        return abs(float((raw or "0").replace(",", "").strip() or 0))
    except Exception:
        return 0.0


def t(el, tag, default=""):
    if el is None:
        return default
    return (el.findtext(tag) or default).strip()


def parse_voucher(v):
    party = t(v, "PARTYLEDGERNAME")
    vno = t(v, "VOUCHERNUMBER")
    vtype = t(v, "VOUCHERTYPENAME")
    is_pdc = t(v, "ISPOSTDATED").lower() in ("yes", "y", "1")
    voucher_date = t(v, "DATE")
    narr = t(v, "NARRATION")

    instrument_date = pdc_actual = bankers = inst_no = bank_name = txn_type = ""
    bank_amount = 0.0
    for bank in v.findall(".//BANKALLOCATIONS.LIST"):
        if not list(bank):
            continue
        instrument_date = t(bank, "INSTRUMENTDATE") or instrument_date
        pdc_actual = t(bank, "PDCACTUALDATE") or pdc_actual
        bankers = t(bank, "BANKERSDATE") or bankers
        inst_no = t(bank, "INSTRUMENTNUMBER") or inst_no
        bank_name = t(bank, "BANKNAME") or bank_name
        txn_type = t(bank, "TRANSACTIONTYPE") or txn_type
        a = money(t(bank, "AMOUNT"))
        if a:
            bank_amount = a

    bills = []
    for led in v.findall(".//ALLLEDGERENTRIES.LIST"):
        for bill in led.findall("BILLALLOCATIONS.LIST"):
            if not list(bill):
                continue
            inv = t(bill, "NAME") or t(bill, "BILLNAME")
            if not inv or inv.upper() in SKIP_BILL_NAMES:
                continue
            bills.append({
                "invoice": inv,
                "amount": money(t(bill, "AMOUNT")),
                "bill_type": t(bill, "BILLTYPE"),
            })

    amount = 0.0
    for led in v.findall(".//ALLLEDGERENTRIES.LIST"):
        a = money(t(led, "AMOUNT"))
        has_bills = any(list(b) for b in led.findall("BILLALLOCATIONS.LIST"))
        has_bank = any(list(b) for b in led.findall("BANKALLOCATIONS.LIST"))
        if has_bills and not has_bank and a:
            amount = a
            break
    if not amount:
        amount = bank_amount

    return {
        "party": re.sub(r"\s+", " ", party).strip(),
        "party_raw": party,
        "voucher_number": vno,
        "voucher_type": vtype,
        "is_post_dated": is_pdc,
        "voucher_date": voucher_date,
        "instrument_date": instrument_date,
        "pdc_actual_date": pdc_actual,
        "bankers_date": bankers,
        "cheque_date_used": instrument_date or voucher_date,
        "instrument_number": inst_no,
        "bank_name": bank_name,
        "txn_type": txn_type,
        "amount": amount,
        "narration": narr,
        "bills": bills,
        "bill_refs": ", ".join(b["invoice"] for b in bills),
    }


def print_row(path, data):
    print("=" * 72)
    print(f"FILE          : {path}")
    print("-" * 72)
    print(f"Party         : {data['party']}")
    if data["party"] != data["party_raw"]:
        print(f"Party (raw)   : {data['party_raw']!r}  <- extra spaces in Tally")
    print(f"Voucher No    : {data['voucher_number']}")
    print(f"Voucher Type  : {data['voucher_type']}")
    print(f"Is Post Dated : {'YES' if data['is_post_dated'] else 'NO'}")
    print(f"Amount        : Rs {data['amount']:,.2f}")
    print()
    print(f"Voucher DATE  : {fmt_date(data['voucher_date'])}   ({data['voucher_date'] or '-'})")
    print(f"Instrument Dt : {fmt_date(data['instrument_date'])}   ({data['instrument_date'] or '-'})")
    print(f"PDC Actual Dt : {fmt_date(data['pdc_actual_date'])}   ({data['pdc_actual_date'] or '-'})")
    print(f"Bankers Date  : {fmt_date(data['bankers_date'])}   ({data['bankers_date'] or '-'})")
    print(f"Cheque date   : {fmt_date(data['cheque_date_used'])}   <- used as cheque_date")
    print()
    print(f"Cheque / Inst#: {data['instrument_number'] or '-'}")
    print(f"Bank / Txn    : {data['bank_name'] or '-'} / {data['txn_type'] or '-'}")
    print(f"Settled bills : {data['bill_refs'] or '-(none)'}")
    for b in data["bills"]:
        print(f"   * Inv {b['invoice']:<12} Rs {b['amount']:>12,.2f}  [{b['bill_type'] or '-'}]")
    if data["narration"]:
        print(f"Narration     : {data['narration'][:120]}")
    print()


def load_xml(path: Path):
    raw = path.read_bytes()
    # Tally exports these vouchers as UTF-16 LE with BOM (ff fe)
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    else:
        # Prefer utf-8; fall back
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-16", errors="ignore")

    ents = sorted(set(re.findall(r"&#\d+;", text)))
    # Hard wipe the known Tally control entity first (most common)
    text = text.replace("&#4;", "").replace("&#04;", "")
    cleaned = clean_tally_xml(text)
    left = sorted(set(re.findall(r"&#\d+;", cleaned)))
    try:
        return ET.fromstring(cleaned), ents, left
    except ET.ParseError as e:
        m = re.search(r"line (\d+)", str(e))
        snippet = ""
        if m:
            ln = int(m.group(1))
            lines = cleaned.splitlines()
            if 0 < ln <= len(lines):
                snippet = lines[ln - 1][:240]
        raise ET.ParseError(
            f"{e}\n  entities_before={ents}\n  entities_after={left}\n  bad_line={snippet!r}"
        ) from e


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    files = [Path(a) for a in argv[1:]] if len(argv) > 1 else [Path(p) for p in DEFAULT_FILES]
    print()
    print("PDC / Receipt XML probe  (temp - display only, no DB write)")
    print(f"Files: {len(files)}")
    print()

    ok = 0
    for path in files:
        if not path.exists():
            print(f"MISSING: {path}")
            continue
        try:
            root, ents, left = load_xml(path)
            print(f"[clean] {path.name}: entities removed={ents} leftover={left or 'none'}")
            vouchers = root.findall(".//VOUCHER")
            if not vouchers:
                print(f"No <VOUCHER> in {path}")
                continue
            for v in vouchers:
                print_row(path, parse_voucher(v))
                ok += 1
        except Exception as e:
            print(f"ERROR parsing {path}:\n{e}\n")

    print("=" * 72)
    print(f"Parsed {ok} voucher(s).")
    print()
    print("Confirmed tags from your sample XML:")
    print("  INSTRUMENTDATE / INSTRUMENTNUMBER / PDCACTUALDATE / BANKERSDATE")
    print("  BILLALLOCATIONS.LIST -> <NAME> = invoice number")
    print("  ISPOSTDATED = Yes/No")
    print()
    print("NOTE: Receipt_965 (MAHADEV) has ISPOSTDATED=No.")
    print("      Current sync filter '$IsPostDated = Yes' would SKIP it.")
    print()
    print("If output looks correct -> tell me to update main sync_engine.py")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
