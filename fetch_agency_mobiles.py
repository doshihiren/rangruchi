"""
Fetches agency mobile numbers from Tally using BGRPBROKERGROUPMOUDF
and updates tally_agency_master table.
Run: venv\Scripts\python.exe fetch_agency_mobiles.py
"""
import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import re, html, psycopg2

DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"

conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# Get all agency names from tally_agency_master
cur.execute("SELECT agency_name FROM tally_agency_master ORDER BY agency_name")
agencies = [r[0] for r in cur.fetchall()]
print(f"Total agencies to check: {len(agencies)}")

updated = 0
for agency in agencies:
    xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE>
<ID>Group</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
<FETCHLIST><FETCH>Name,UDF:BGrpBrokerGroupMoUdf</FETCH></FETCHLIST>
<OBJECTID>{agency}</OBJECTID>
</DESC></BODY></ENVELOPE>"""

    try:
        r = _post_xml(xml)
        if 'ERRORMSG' in r:
            continue
        mob = re.search(r'(?i)BGRPBROKERGROUPMOUDF[^>]*>(.*?)<', r)
        if mob and mob.group(1).strip():
            mobile = re.sub(r'[^0-9]', '', mob.group(1).strip())[-10:]
            if len(mobile) == 10:
                cur.execute("UPDATE tally_agency_master SET mobile=%s WHERE agency_name=%s", (mobile, agency))
                if cur.rowcount:
                    print(f"  {agency[:45]:<45} → {mobile}")
                    updated += 1
    except Exception as e:
        print(f"  Error {agency}: {e}")

conn.commit()
print(f"\nUpdated {updated} agency mobiles")
cur.close()
conn.close()
