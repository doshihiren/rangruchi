import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import re, psycopg2

DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"

parties = [
    'YOGESH TRADING COMPANY',
    'RAJA INTERNATIONAL LIFESTYLE PRIVATE LIMITED (MZFR)',
    'RADHE RADHE ENTERPRISES',
    'ANAPURNA SALES',
    'JAI BHAWANI TRADING',
    'GH ENTERPRISES INC',
    'RAJA TEX (DALTOGANJ)',
    'MTA TEXTILE AGENCY',
    'SHUBHAM PRAKASH JAIN',
    'ACADEMY FOR COMPUTER SOLUTIONS',
    'KHUSHBHU DEVI SUKESH',
    'THE CHENNAI SILKS',
    'SHYAMA SHYAM FABRICS PVT LTD',
]

print(f"{'PARTY':<50} {'UDF AGENCY':<35} {'PARENT'}")
print("-"*110)

conn = psycopg2.connect(**DB)
cur  = conn.cursor()

for party in parties:
    # Fetch from Tally
    xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE>
<ID>Ledger</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
<FETCHLIST><FETCH>Name,Parent,UDF:BMstLedAgencyNameUdf</FETCH></FETCHLIST>
<OBJECTID>{party}</OBJECTID>
</DESC></BODY></ENVELOPE>"""

    r = _post_xml(xml)
    agency = re.search(r'BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)</', r, re.IGNORECASE)
    parent = re.search(r'<PARENT>(.*?)</PARENT>', r)
    error  = 'ERRORMSG' in r

    ag = (agency.group(1).strip() if agency else '').strip()
    pt = (parent.group(1).strip() if parent else '').strip()

    # Skip self-ref
    if ag.upper() == party.upper(): ag = ''

    status = "NOT IN TALLY" if error else (ag if ag else "EMPTY")
    print(f"  {party[:48]:<50} {status:<35} {pt}")

    if ag and not error:
        # Update in DB
        cur.execute("UPDATE tickets SET agency_name=%s WHERE party_name=%s", (ag, party))
        cur.execute("""INSERT INTO manual_agency_override(party_name,agency_name)
                       VALUES(%s,%s) ON CONFLICT(party_name) DO UPDATE SET agency_name=EXCLUDED.agency_name""",
                    (party, ag))

conn.commit()
cur.close()
conn.close()
print("\nUpdated parties with agency from Tally")
