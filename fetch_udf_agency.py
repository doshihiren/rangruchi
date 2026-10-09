import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import re

COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"
parties = [
    'YOGESH TRADING COMPANY','JAI BHAWANI TRADING',
    'ANAPURNA SALES','RADHE RADHE ENTERPRISES',
    'GH ENTERPRISES INC','SHYAMA SHYAM FABRICS PVT LTD',
    'RAJA TEX (DALTOGANJ)','SHUBHAM PRAKASH JAIN',
]

XML = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>AgencyCheck</ID></HEADER><BODY><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY>
</STATICVARIABLES>
<TDL><TDLMESSAGE>
<COLLECTION NAME="AgencyCheck" ISMODIFY="No">
<TYPE>Ledger</TYPE>
<FETCH>Name,UDF:BMstLedAgencyNameUdf,Parent</FETCH>
<FILTER>F1</FILTER>
</COLLECTION>
<SYSTEM TYPE="Formulae" NAME="F1">$Parent = "Sundry Debtors" OR $Parent = "ARDTH GROUP"</SYSTEM>
</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""

r = _post_xml(XML)
names   = re.findall(r'<NAME>(.*?)</NAME>', r)
agencies= re.findall(r'BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)</', r, re.IGNORECASE)
parents = re.findall(r'<PARENT>(.*?)</PARENT>', r)

print(f"Fetched {len(names)} ledgers")
for i,n in enumerate(names):
    if any(p.upper() in n.upper() for p in ['YOGESH','JAI BHAWANI','ANAPURNA','RADHE','GH ENTERPRISE','SHYAMA','RAJA TEX','SHUBHAM']):
        ag = agencies[i] if i < len(agencies) else '—'
        pt = parents[i] if i < len(parents) else '—'
        print(f"  {n}: agency={ag!r} parent={pt}")
