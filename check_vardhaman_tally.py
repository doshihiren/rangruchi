import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import re, html

COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"

# Fetch VARDHAMAN AGENCY group from Tally
xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE>
<ID>Group</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
<FETCHLIST><FETCH>Name,UDF:BGrpBrokerGroupMoUdf</FETCH></FETCHLIST>
<OBJECTID>VARDHAMAN AGENCY (JITUBHAI)</OBJECTID>
</DESC></BODY></ENVELOPE>"""

r = _post_xml(xml)
mobile = re.search(r'(?i)BGRPBROKERGROUPMOUDF[^>]*>(.*?)<', r)
name   = re.search(r'<NAME>(.*?)</NAME>', r)
print(f"Name: {name.group(1) if name else 'NOT FOUND'}")
print(f"Mobile: {mobile.group(1) if mobile else 'NOT FOUND'}")

# Also check M S RAMAYYA party UDF
xml2 = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE>
<ID>Ledger</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
<FETCHLIST><FETCH>Name,UDF:BMstLedAgencyNameUdf,LedgerMobile</FETCH></FETCHLIST>
<OBJECTID>M S RAMAYYA SHOPPING MALL</OBJECTID>
</DESC></BODY></ENVELOPE>"""

r2 = _post_xml(xml2)
agency = re.search(r'(?i)BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)<', r2)
mob    = re.search(r'<LEDGERMOBILE>(.*?)</LEDGERMOBILE>', r2)
print(f"\nM S RAMAYYA agency in Tally: {agency.group(1) if agency else 'NOT FOUND'}")
print(f"M S RAMAYYA mobile in Tally: {mob.group(1) if mob else 'NOT FOUND'}")
