import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import re

COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"

xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>LedCheck</ID></HEADER><BODY><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY>
</STATICVARIABLES>
<TDL><TDLMESSAGE>
<COLLECTION NAME="LedCheck" ISMODIFY="No">
<TYPE>Ledger</TYPE>
<FETCH>Name,UDF:BMstLedAgencyNameUdf,LedgerMobile,Parent</FETCH>
<FILTER>F1</FILTER>
</COLLECTION>
<SYSTEM TYPE="Formulae" NAME="F1">$$InWords:$Name CONTAINS "SUPER KIDS"</SYSTEM>
</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""

r = _post_xml(xml)
print("Response:")
print(r[:2000])

# Parse
names   = re.findall(r'<NAME>(.*?)</NAME>', r)
agencies= re.findall(r'(?i)BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)<', r)
mobiles = re.findall(r'<LEDGERMOBILE>(.*?)</LEDGERMOBILE>', r)

for i,n in enumerate(names):
    ag = agencies[i] if i < len(agencies) else '—'
    mob = mobiles[i] if i < len(mobiles) else '—'
    print(f"\n{n}: agency={ag} mobile={mob}")
