"""
auto_agency_mobile_sync.py
Fetches agency mobiles from Master.xml GROUP blocks and updates tally_agency_master.
Called automatically on every Tally Sync.
Run manually: venv\Scripts\python.exe auto_agency_mobile_sync.py
"""
import re, html, psycopg2, os, sys

XML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Master.xml")
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")

def sync_agency_mobiles(xml_path=XML_PATH):
    if not os.path.exists(xml_path):
        print(f"Master.xml not found: {xml_path}")
        return 0

    with open(xml_path,"rb") as f: raw = f.read()
    try: text = raw.decode("utf-16-le", errors="ignore")
    except: text = raw.decode("utf-8", errors="ignore")

    conn = psycopg2.connect(**DB)
    cur  = conn.cursor()

    cur.execute("SELECT agency_name FROM tally_agency_master")
    existing_rows = cur.fetchall()

    def norm_name(value):
        return re.sub(r"\\s+", " ", html.unescape(str(value or "")).strip()).upper()

    existing = {norm_name(r[0]): r[0] for r in existing_rows}

    updated = 0
    for m in re.finditer(r'<GROUP\s+NAME="([^"]+)"[^>]*>(.*?)</GROUP>', text, re.DOTALL):
        name = html.unescape(m.group(1).strip())
        block = m.group(2)

        # Match GROUP names case-insensitively and ignoring repeated whitespace.
        existing_name = existing.get(norm_name(name))
        if not existing_name:
            continue

        # Tally stores the agency mobile in the broker-group UDF.
        mob = re.search(
            r'(?is)BGRPBROKERGROUPMOUDF[^>]*>(.*?)<',
            block
        )

        if mob and mob.group(1).strip():
            mobile = re.sub(
                r'[^0-9]',
                '',
                re.split(r'[/,;&]', mob.group(1))[0]
            )[-10:]

            if len(mobile) == 10:
                # IMPORTANT: column is agency_mobile, not mobile.
                cur.execute(
                    '''
                    UPDATE tally_agency_master
                    SET agency_mobile=%s
                    WHERE agency_name=%s
                      AND (agency_mobile IS NULL OR agency_mobile <> %s)
                    ''',
                    (mobile, existing_name, mobile)
                )

                if cur.rowcount:
                    updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Agency mobiles synced: {updated} updated")
    return updated

if __name__ == "__main__":
    sync_agency_mobiles()
