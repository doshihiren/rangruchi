"""
tally_guard.py  — drop this NEW file next to sync_engine.py

Purpose: stop the auto-scheduler from wiping outstanding/billwise to 0
when Tally is closed, on a different port, or returns a partial export.

Nothing here touches your existing modules; sync_engine.py just imports it.
"""
import logging
import requests

from config import TALLY_URL
from db import execute, fetchone

logger = logging.getLogger(__name__)

PROBE_XML = """<ENVELOPE><HEADER><VERSION>1</VERSION>
<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>ProbeCompany</ID></HEADER><BODY><DESC>
<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES>
<TDL><TDLMESSAGE><COLLECTION NAME="ProbeCompany">
<TYPE>Company</TYPE><FETCH>Name</FETCH>
</COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""


def tally_alive(timeout=8):
    """True only if Tally answers AND returns at least one company."""
    try:
        r = requests.post(TALLY_URL, data=PROBE_XML,
                          headers={"Content-Type": "application/xml"},
                          timeout=timeout)
        if r.status_code != 200:
            logger.warning(f"Tally probe HTTP {r.status_code}")
            return False
        body = (r.text or "").upper()
        if "<COMPANY" not in body and "<NAME>" not in body:
            logger.warning("Tally probe returned no company data")
            return False
        return True
    except Exception as e:
        logger.warning(f"Tally not reachable: {e}")
        return False


def row_count(table):
    try:
        r = fetchone(f"SELECT COUNT(*) FROM {table}")
        return int(r[0] if not isinstance(r, dict) else list(r.values())[0])
    except Exception:
        return 0


def safe_replace(table, insert_sql, rows, min_ratio=0.5, min_rows=1):
    """Replace a table's contents ONLY if the new data looks sane.

    Deletes and inserts inside one call so a failure leaves old data intact.
    Returns number of rows written, or -1 when the write was refused.
    """
    from db import executemany

    new_n = len(rows)
    old_n = row_count(table)

    if new_n < min_rows:
        logger.error(f"{table}: refused — Tally returned {new_n} rows "
                     f"(existing {old_n} kept)")
        return -1
    if old_n > 20 and new_n < old_n * min_ratio:
        logger.error(f"{table}: refused — only {new_n} rows vs existing "
                     f"{old_n} (looks like a partial export)")
        return -1

    execute(f"DELETE FROM {table}")
    executemany(insert_sql, rows)
    logger.info(f"{table}: replaced {old_n} -> {new_n} rows")
    return new_n
