import sys; sys.path.insert(0,".")
from sync_engine import _post_xml
import re

COMPANY = "RANGRUCHI FASHION PVT LTD - (from 1-Apr-25)"

parties = ['SARALA SILKS (PALAKKAD)', 'KIRAN TEXTILE MILLS']

for party in parties:
    xml = f"""<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE>
<ID>Ledger</ID></HEADER><BODY><DESC>
<STATICVARIABLES>
<SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY>
</STATICVARIABLES>
<FETCHLIST>
<FETCH>NAME,PARENT,UDF:BMstLedAgencyNameUdf,LEDGERMOBILE,PHONENUMBER</FETCH>
</FETCHLIST>
<OBJECTID>{party}</OBJECTID>
</DESC></BODY></ENVELOPE>"""

    r = _post_xml(xml)
    agency = re.search(r'BMSTLEDAGENCYNAMEUDF[^>]*>(.*?)</', r, re.IGNORECASE)
    parent = re.search(r'<PARENT>(.*?)</PARENT>', r)
    mobile = re.search(r'<LEDGERMOBILE>(.*?)</LEDGERMOBILE>', r)
    print(f"\n{party}")
    print(f"  agency={agency.group(1) if agency else '—'}")
    print(f"  parent={parent.group(1) if parent else '—'}")
    print(f"  mobile={mobile.group(1) if mobile else '—'}")
    # Show raw for debugging
    if not agency or not agency.group(1).strip():
        print(f"  raw: {r[:500]}")
