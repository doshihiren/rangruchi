"""
sync_tally_master.py  v3 — streaming parser (handles 200 MB+ Master.xml)

Fixes:
  1. Mobile now read from LEDGERCONTACTLIST.LIST -> <NAME>Primary Mobile No.</NAME>
     + <PHONENUMBER>, plus LEDGERMOBILE / CONTACTDETAILS.LIST fallbacks.
  2. Agency name read from UDF:BMstLedAgencyNameUdf even when it carries a
     DESC="..." attribute or sits on a nested line.
  3. NO TRUNCATE. Pure upsert, and a blank value never overwrites a good one
     (COALESCE(NULLIF(...))), so a bad/partial export can no longer wipe data.
  4. Streams the file in chunks — constant memory even for a 200 MB export.

Run:  venv\\Scripts\\python.exe sync_tally_master.py Master.xml
"""
import sys, os, re, html, io

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "psycopg2-binary", "--quiet"])
    import psycopg2

from datetime import datetime

DB = dict(host="localhost", port=5432, dbname="tally_erp",
          user="postgres", password="7sW9U0JRHzvxrYkLe9kr")

XML_PATH = sys.argv[1] if len(sys.argv) > 1 else "tally_export.xml"
if not os.path.exists(XML_PATH):
    print(f"XML file not found: {XML_PATH}")
    sys.exit(1)

print(f"Reading: {XML_PATH}  ({os.path.getsize(XML_PATH)//(1024*1024)} MB)")


# ── encoding sniff (Tally exports UTF-16LE or UTF-8) ───────────────
def detect_encoding(path):
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head[:2] == b"\xff\xfe":
        return "utf-16-le"
    if head[:2] == b"\xfe\xff":
        return "utf-16-be"
    if len(head) >= 2 and head[0] != 0 and head[1] == 0:
        return "utf-16-le"     # no BOM but clearly UTF-16LE
    return "utf-8"


ENC = detect_encoding(XML_PATH)
print(f"Encoding detected: {ENC}")

LEDGER_RE = re.compile(r'<LEDGER\s+NAME="([^"]*)"[^>]*>(.*?)</LEDGER>', re.DOTALL)


def iter_ledgers(path, encoding, chunk_chars=4_000_000):
    """Yield (name, block) for every <LEDGER> without loading the whole file."""
    buf = ""
    with io.open(path, "r", encoding=encoding, errors="ignore") as fh:
        while True:
            chunk = fh.read(chunk_chars)
            if not chunk:
                break
            buf += chunk
            last_end = 0
            for m in LEDGER_RE.finditer(buf):
                yield html.unescape(m.group(1).strip()), m.group(2)
                last_end = m.end()
            if last_end:
                buf = buf[last_end:]
            # guard: if a single ledger is absurdly large, drop stale head
            if len(buf) > 20_000_000:
                cut = buf.rfind("<LEDGER ")
                buf = buf[cut:] if cut > 0 else ""
        for m in LEDGER_RE.finditer(buf):
            yield html.unescape(m.group(1).strip()), m.group(2)


# ── field helpers ──────────────────────────────────────────────────
def get_first(tag, block):
    for v in re.findall(f"<{tag}>(.*?)</{tag}>", block, re.DOTALL):
        v = html.unescape(v.strip())
        if v:
            return v
    return ""


def get_scoped(tag, parent_tag, block):
    parent = re.search(f"<{parent_tag}>(.*?)</{parent_tag}>", block, re.DOTALL)
    if not parent:
        return ""
    return get_first(tag, parent.group(1))


def getall(tag, block):
    return [html.unescape(v.strip())
            for v in re.findall(f"<{tag}>(.*?)</{tag}>", block, re.DOTALL)
            if v.strip()]


def getudf(udfname, block):
    """Match <UDF:NAME DESC="..."> value </UDF:NAME> and UDF_NAME variants."""
    pat = rf"<\s*UDF[:_]{udfname}\b[^>]*>(.*?)<\s*/\s*UDF[:_]{udfname}\s*>"
    for v in re.findall(pat, block, re.IGNORECASE | re.DOTALL):
        v = html.unescape(re.sub(r"<[^>]+>", " ", v)).strip()
        if v:
            return v
    # last resort: opening tag followed by text
    for v in re.findall(rf"UDF[:_]{udfname}[^>]*>\s*([^\n<]+?)\s*<",
                        block, re.IGNORECASE):
        v = html.unescape(v.strip())
        if v:
            return v
    return ""


CONTACT_RE = re.compile(
    r"<LEDGERCONTACTLIST\.LIST>(.*?)</LEDGERCONTACTLIST\.LIST>", re.DOTALL)


def digits10(raw):
    if not raw:
        return ""
    first = re.split(r"[/,;&]", str(raw))[0]
    d = re.sub(r"[^0-9]", "", first)
    return d[-10:] if len(d) >= 10 else ""


def get_mobile(block):
    """1) LEDGERCONTACTLIST.LIST 'Primary Mobile No.'  2) any contact-list phone
       3) LEDGERMOBILE  4) CONTACTDETAILS.LIST PHONENUMBER"""
    fallback = ""
    for c in CONTACT_RE.findall(block):
        cname = get_first("NAME", c).lower()
        phone = digits10(get_first("PHONENUMBER", c) or get_first("MOBILENO", c))
        if not phone:
            continue
        if "mobile" in cname:          # Primary Mobile No. / Mobile
            return phone
        fallback = fallback or phone
    m = digits10(get_first("LEDGERMOBILE", block)) \
        or digits10(get_first("MOBILENO", block)) \
        or digits10(get_scoped("PHONENUMBER", "CONTACTDETAILS.LIST", block))
    return m or fallback


SKIP_PARENTS = {
    "Sundry Debtors", "Sundry Creditors", "", "TRANSPORTS CREDITORS", "CASH",
    "COMMISSION CREDITORS", "SELF", "KARIGAR CREDITORS", "Fixed Assets",
    "MSME CREDITORS (VINODBHAI)", "MSME CREDITORS (PANKAJBHAI)", "ARDTH GROUP",
    "AGENCY GROUP", "DIRECT", "CREDITORS FOR EXPENSES", "MSME CREDITORS",
    "Bank Accounts", "Capital Account",
}
AGENCY_HINTS = ["AGENCY", "ENTERP", "TRADER", "TEXTILE", "COLLECTION",
                "GROUP", "SALES", "MARKETING", "SAREE"]

parties, agencies = [], {}
scanned = 0

for name, block in iter_ledgers(XML_PATH, ENC):
    scanned += 1
    if scanned % 5000 == 0:
        print(f"  ...scanned {scanned} ledgers, kept {len(parties)}")

    mobile = get_mobile(block)
    state = get_scoped("STATE", "LEDMAILINGDETAILS.LIST", block) \
        or get_first("LEDSTATENAME", block)
    pos = get_scoped("PLACEOFSUPPLY", "LEDGSTREGDETAILS.LIST", block)
    gstin = get_scoped("GSTIN", "LEDGSTREGDETAILS.LIST", block) \
        or get_first("PARTYGSTIN", block)
    gst_type = get_scoped("GSTREGISTRATIONTYPE", "LEDGSTREGDETAILS.LIST", block)

    agency_name = getudf("BMSTLEDAGENCYNAMEUDF", block)

    # keep party ledgers only (agency name alone is also a valid signal)
    if not (mobile or pos or gstin or agency_name):
        continue

    if not agency_name:
        p = get_first("PARENT", block)
        cand = p if p not in SKIP_PARENTS else ""
        if cand and any(k in cand.upper() for k in AGENCY_HINTS):
            agency_name = cand

    mailing = get_first("MAILINGNAME", block)
    pincode = get_scoped("PINCODE", "LEDMAILINGDETAILS.LIST", block) \
        or get_first("PINCODE", block)
    country = get_scoped("COUNTRY", "LEDMAILINGDETAILS.LIST", block)
    address = ", ".join(getall("ADDRESS", block))

    wa_raw = digits10(getudf("MIWHATSAPPNUM", block))
    whatsapp = wa_raw

    transport = getudf("BMSTLEDTRANSPORTUDF", block)
    place_udf = getudf("BMSTLEDPLACEUDF", block)
    distance_km = getudf("BMSTLEDDISTANCEUDF", block)
    agency_mobile = digits10(getudf("BGRPBROKERGROUPMOUDF", block))

    if agency_name and agency_mobile:
        agencies[agency_name] = {"mobile": agency_mobile, "contact_person": None}

    parties.append({
        "party_name": name, "mailing_name": mailing, "mobile": mobile,
        "whatsapp": whatsapp, "state": state, "place_of_supply": pos,
        "gstin": gstin, "gst_type": gst_type, "address": address,
        "pincode": pincode, "country": country, "agency_name": agency_name,
        "transport": transport, "place_udf": place_udf,
        "distance_km": distance_km,
    })

print(f"\nScanned {scanned} ledgers -> kept {len(parties)} parties, "
      f"{len(agencies)} agencies with mobile")

with_mob = sum(1 for p in parties if p["mobile"])
with_ag = sum(1 for p in parties if p["agency_name"])
print(f"In-file coverage: mobile {with_mob}/{len(parties)}, "
      f"agency {with_ag}/{len(parties)}")

print("\nSample (first 5):")
for p in parties[:5]:
    print(f"  {p['party_name'][:35]:35s} | mob={p['mobile']:12s} | "
          f"agency={p['agency_name'][:25]:25s} | state={p['state']}")

# ── SAFETY GATE: refuse to load a clearly broken export ────────────
if len(parties) == 0:
    print("\nABORT: 0 parties parsed. Existing data left untouched.")
    sys.exit(2)

print("\nConnecting to DB...")
conn = psycopg2.connect(**DB)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM tally_party_master")
existing = cur.fetchone()[0]
if existing > 100 and len(parties) < existing * 0.5:
    print(f"ABORT: parsed {len(parties)} parties but DB already has {existing}. "
          "Export looks partial — nothing written.")
    cur.close(); conn.close()
    sys.exit(3)

# NOTE: no TRUNCATE. Upsert only; blanks never overwrite existing values.
party_sql = """
INSERT INTO tally_party_master (
    party_name, mailing_name, mobile, whatsapp,
    state, place_of_supply, gstin, gst_type,
    address, pincode, country,
    agency_name, transport, place_udf, distance_km, last_synced_at
) VALUES (
    %(party_name)s, %(mailing_name)s, %(mobile)s, %(whatsapp)s,
    %(state)s, %(place_of_supply)s, %(gstin)s, %(gst_type)s,
    %(address)s, %(pincode)s, %(country)s,
    %(agency_name)s, %(transport)s, %(place_udf)s, %(distance_km)s, NOW()
)
ON CONFLICT (party_name) DO UPDATE SET
    mailing_name    = COALESCE(NULLIF(EXCLUDED.mailing_name,''),    tally_party_master.mailing_name),
    mobile          = COALESCE(NULLIF(EXCLUDED.mobile,''),          tally_party_master.mobile),
    whatsapp        = COALESCE(NULLIF(EXCLUDED.whatsapp,''),        tally_party_master.whatsapp),
    state           = COALESCE(NULLIF(EXCLUDED.state,''),           tally_party_master.state),
    place_of_supply = COALESCE(NULLIF(EXCLUDED.place_of_supply,''), tally_party_master.place_of_supply),
    gstin           = COALESCE(NULLIF(EXCLUDED.gstin,''),           tally_party_master.gstin),
    gst_type        = COALESCE(NULLIF(EXCLUDED.gst_type,''),        tally_party_master.gst_type),
    address         = COALESCE(NULLIF(EXCLUDED.address,''),         tally_party_master.address),
    pincode         = COALESCE(NULLIF(EXCLUDED.pincode,''),         tally_party_master.pincode),
    country         = COALESCE(NULLIF(EXCLUDED.country,''),         tally_party_master.country),
    agency_name     = COALESCE(NULLIF(EXCLUDED.agency_name,''),     tally_party_master.agency_name),
    transport       = COALESCE(NULLIF(EXCLUDED.transport,''),       tally_party_master.transport),
    place_udf       = COALESCE(NULLIF(EXCLUDED.place_udf,''),       tally_party_master.place_udf),
    distance_km     = COALESCE(NULLIF(EXCLUDED.distance_km,''),     tally_party_master.distance_km),
    last_synced_at  = NOW()
"""

ok = 0
for p in parties:
    try:
        cur.execute(party_sql, p)
        ok += 1
    except Exception as e:
        print(f"  Error: {p['party_name']}: {e}")
        conn.rollback()
conn.commit()
print(f"\ntally_party_master: {ok}/{len(parties)} upserted")

# agencies (best-effort; table may not exist in older installs)
try:
    for ag, meta in agencies.items():
        cur.execute("""
            INSERT INTO tally_agency_master (agency_name, agency_mobile)
            VALUES (%s,%s)
            ON CONFLICT (agency_name) DO UPDATE SET
              agency_mobile = COALESCE(NULLIF(EXCLUDED.agency_mobile,''),
                                       tally_agency_master.agency_mobile)
        """, (ag, meta["mobile"]))
    conn.commit()
    print(f"tally_agency_master: {len(agencies)} upserted")
except Exception as e:
    conn.rollback()
    print(f"agency master skipped: {e}")

cur.execute("SELECT COUNT(*) FROM tally_party_master WHERE COALESCE(mobile,'')<>''")
wm = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM tally_party_master WHERE COALESCE(agency_name,'')<>''")
wa = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM tally_party_master WHERE COALESCE(place_of_supply,'')<>''")
wp = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM tally_party_master")
t = cur.fetchone()[0] or 1
print(f"Mobile coverage : {wm}/{t} ({wm*100//t}%)")
print(f"Agency coverage : {wa}/{t} ({wa*100//t}%)")
print(f"Place of supply : {wp}/{t} ({wp*100//t}%)")

print("\nTop agencies:")
cur.execute("""
    SELECT agency_name, COUNT(*) c FROM tally_party_master
    WHERE COALESCE(agency_name,'') <> ''
    GROUP BY agency_name ORDER BY c DESC LIMIT 15
""")
for row in cur.fetchall():
    print(f"  {row[0][:45]:45s}: {row[1]}")

cur.close()
conn.close()
print(f"\nDone at {datetime.now():%Y-%m-%d %H:%M:%S}")


def sync_agency_fullnames():
    """Push full agency names from master tables into tickets.
    Never overwrites a longer name with a shorter one."""
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    cur.execute(r"""
        UPDATE tally_party_master tpm SET agency_name = tam.agency_name
        FROM tally_agency_master tam
        WHERE regexp_replace(UPPER(tam.agency_name),'\s+',' ','g')
            LIKE regexp_replace(UPPER(tpm.agency_name),'\s+',' ','g') || '%%'
        AND LENGTH(tam.agency_name) > LENGTH(COALESCE(tpm.agency_name,''))
        AND COALESCE(TRIM(tpm.agency_name),'') <> ''
        AND LOWER(tpm.agency_name) NOT IN ('nan','none','null','self','cash')
    """)
    conn.commit(); print(f"  tpm agency expanded: {cur.rowcount}")

    cur.execute(r"""
        UPDATE tickets t SET agency_name = tpm.agency_name
        FROM tally_party_master tpm
        WHERE regexp_replace(UPPER(tpm.party_name),'\s+',' ','g')
            = regexp_replace(UPPER(t.party_name),'\s+',' ','g')
        AND COALESCE(TRIM(tpm.agency_name),'') <> ''
        AND LOWER(tpm.agency_name) NOT IN ('nan','none','null','self','cash')
        AND LENGTH(tpm.agency_name) >= LENGTH(COALESCE(t.agency_name,''))
    """)
    conn.commit(); print(f"  tickets agency from tpm: {cur.rowcount}")

    # mobiles: fill only, never blank out
    cur.execute("""
        UPDATE tickets t SET party_mobile = tpm.mobile
        FROM tally_party_master tpm
        WHERE tpm.party_name = t.party_name
        AND COALESCE(TRIM(tpm.mobile),'') <> ''
        AND (t.party_mobile IS NULL OR LENGTH(TRIM(t.party_mobile)) < 10)
    """)
    conn.commit(); print(f"  tickets mobile filled: {cur.rowcount}")

    cur.execute(r"""
        UPDATE tickets t SET agency_name = tam.agency_name
        FROM tally_agency_master tam
        WHERE regexp_replace(UPPER(tam.agency_name),'\s+',' ','g')
                LIKE regexp_replace(UPPER(t.agency_name),'\s+',' ','g') || '%%'
        AND LENGTH(tam.agency_name) > LENGTH(COALESCE(t.agency_name,''))
        AND COALESCE(TRIM(t.agency_name),'') <> ''
        AND LOWER(t.agency_name) NOT IN ('nan','none','null')
    """)
    conn.commit(); print(f"  tickets agency expanded: {cur.rowcount}")

    try:
        cur.execute("""
            UPDATE tickets t SET agency_name = mo.agency_name
            FROM manual_agency_override mo
            WHERE t.party_name = mo.party_name
        """)
        conn.commit(); print(f"  manual overrides applied: {cur.rowcount}")
    except Exception as e:
        conn.rollback(); print(f"  manual override skipped: {e}")

    cur.close(); conn.close()
    print("Agency sync complete")


if __name__ != "__main__":
    pass
