import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import re

COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"

xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE>
<ID>Ledger</ID></HEADER><BODY><DESC>
<STATICVARIABLES>
<SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY>
</STATICVARIABLES>
<FETCHLIST>
<FETCH>Name,Parent,UDF:BMstLedAgencyNameUdf,LedgerMobile</FETCH>
</FETCHLIST>
<OBJECTID>SUPER KIDS WEAR (WAGHOLI)</OBJECTID>
</DESC></BODY></ENVELOPE>"""

r = _post_xml(xml)
agency = re.search(r'(?i)BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)<', r)
mobile = re.search(r'<LEDGERMOBILE>(.*?)</LEDGERMOBILE>', r)
parent = re.search(r'<PARENT>(.*?)</PARENT>', r)
print(f"agency: {agency.group(1) if agency else 'NOT FOUND'}")
print(f"mobile: {mobile.group(1) if mobile else 'NOT FOUND'}")
print(f"parent: {parent.group(1) if parent else 'NOT FOUND'}")
if 'ERRORMSG' in r:
    print(f"Error: {r}")
