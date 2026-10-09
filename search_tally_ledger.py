import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import xml.etree.ElementTree as ET, re

COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"

for keyword in ['SARALA', 'KIRAN TEXTILE']:
    xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>LedSearch</ID></HEADER><BODY><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY>
</STATICVARIABLES>
<TDL><TDLMESSAGE>
<COLLECTION NAME="LedSearch" ISMODIFY="No">
<TYPE>Ledger</TYPE>
<FETCH>Name,Parent,UDF:BMstLedAgencyNameUdf,LedgerMobile</FETCH>
<FILTER>F1</FILTER>
</COLLECTION>
<SYSTEM TYPE="Formulae" NAME="F1">$$InWords:$Name CONTAINS "{keyword}"</SYSTEM>
</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""

    r = _post_xml(xml)
    names = re.findall(r'<NAME>(.*?)</NAME>', r)
    agencies = re.findall(r'BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)</', r, re.IGNORECASE)
    print(f"\nSearch '{keyword}':")
    for i,n in enumerate(names[:5]):
        ag = agencies[i] if i < len(agencies) else '—'
        print(f"  {n} → agency={ag}")
