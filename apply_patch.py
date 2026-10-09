"""
RecoveryOS auto-patcher  (run from your project root)

    venv\\Scripts\\python.exe apply_patch.py

What it does (idempotent - safe to run twice):
  * backs up sync_engine.py / auto_sync_scheduler.py to *.bak_<timestamp>
  * sync_engine.py : adds tally_guard import, replaces the two DELETE+INSERT
                     blocks with safe_replace(), guards run_full_sync(),
                     extends <FETCH>, fixes the mobile + agency UDF parsing
  * auto_sync_scheduler.py : skips the job when Tally is offline
Anything it cannot find is reported as SKIP so you can do that bit by hand.
"""

import os
import re
import shutil
import sys
from datetime import datetime

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
ok, skip = [], []


def backup(path):
    dst = f"{path}.bak_{STAMP}"
    shutil.copy2(path, dst)
    print(f"  backup -> {dst}")


def load(path):
    if not os.path.exists(path):
        skip.append(f"{path} not found in {os.getcwd()}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def sub_once(text, pattern, repl, label, flags=re.S):
    """Regex replace exactly one occurrence; report success/failure."""
    new, n = re.subn(pattern, lambda m: repl, text, count=1, flags=flags)
    if n:
        ok.append(label)
        return new
    skip.append(label)
    return text


# --------------------------------------------------------------- sync_engine
ENGINE = "sync_engine.py"
src = load(ENGINE)
if src:
    print(f"\n[1/2] {ENGINE}")
    backup(ENGINE)

    # -- import ------------------------------------------------------------
    if "from tally_guard import" in src:
        ok.append("import tally_guard (already present)")
    else:
        m = re.search(r"^(from\s+db\s+import[^\n]*\n)", src, re.M)
        if m:
            src = src[: m.end()] + "from tally_guard import tally_alive, safe_replace\n" + src[m.end():]
            ok.append("import tally_guard")
        else:                       # fall back: after last top-level import
            m = list(re.finditer(r"^(?:import|from)[^\n]*\n", src, re.M))
            if m:
                p = m[-1].end()
                src = src[:p] + "from tally_guard import tally_alive, safe_replace\n" + src[p:]
                ok.append("import tally_guard (after last import)")
            else:
                skip.append("import tally_guard")

    if not re.search(r"^import re\b", src, re.M):
        src = "import re\n" + src
        ok.append("import re")

    # -- outstanding: DELETE + executemany -> safe_replace ------------------
    if "safe_replace(\n            \"outstanding\"" in src or 'safe_replace("outstanding"' in src:
        ok.append("outstanding safe_replace (already present)")
    else:
        src = sub_once(
            src,
            r'[ \t]*execute\(\s*["\']DELETE FROM outstanding["\']\s*\)\s*\n'
            r'[ \t]*executemany\(\s*(?P<q>["\'].*?["\'])\s*,\s*rows\s*\)',
            '        written = safe_replace("outstanding",\n'
            '            "INSERT INTO outstanding(party_name,balance,synced_at) VALUES(%s,%s,%s)",\n'
            '            rows)\n'
            '        if written < 0:\n'
            '            _log_sync("outstanding", 0, "Skipped", "suspicious row count - old data kept")\n'
            '            return 0',
            "outstanding safe_replace",
        )

    # -- billwise ----------------------------------------------------------
    if 'safe_replace("billwise"' in src:
        ok.append("billwise safe_replace (already present)")
    else:
        src = sub_once(
            src,
            r'[ \t]*execute\(\s*["\']DELETE FROM billwise["\']\s*\)\s*\n'
            r'[ \t]*executemany\(\s*(?:"""|\'\'\'|["\']).*?(?:"""|\'\'\'|["\'])\s*,\s*rows\s*\)',
            '        written = safe_replace("billwise",\n'
            '            """INSERT INTO billwise(party_name,invoice_date,invoice_no,overdue_days,pending_amount,synced_at)\n'
            '               VALUES(%s,%s,%s,%s,%s,%s)""",\n'
            '            rows)\n'
            '        if written < 0:\n'
            '            _log_sync("billwise", 0, "Skipped", "suspicious row count - old data kept")\n'
            '            return 0',
            "billwise safe_replace",
        )

    # -- run_full_sync guard ----------------------------------------------
    if "FULL SYNC ABORTED" in src:
        ok.append("run_full_sync guard (already present)")
    else:
        m = re.search(r"def run_full_sync\([^)]*\)[^\n]*\n(?P<body>(?:[ \t]*(?:\"\"\".*?\"\"\"|'''.*?''')\s*\n)?)", src, re.S)
        if m:
            p = m.end()
            guard = (
                '    if not tally_alive():\n'
                '        try:\n'
                '            _log_sync("full_sync", 0, "Skipped", "Tally not reachable")\n'
                '        except Exception:\n'
                '            pass\n'
                '        print("Tally not reachable - FULL SYNC ABORTED, existing data kept")\n'
                '        return {"status": "skipped", "reason": "Tally not reachable"}\n'
            )
            src = src[:p] + guard + src[p:]
            ok.append("run_full_sync guard")
        else:
            skip.append("run_full_sync guard")

    # -- FETCH list --------------------------------------------------------
    def fix_fetch(m):
        inner = m.group(1)
        for tag in ("PhoneNumber", "Mobile", "LedgerContactList",
                    "UDF:BMstLedAgencyNameUdf", "UDF:BEIBrokerNameUdf",
                    "UDF:BGRPBrokerGroupMoUdf", "UDF:BMstLedPlaceUdf"):
            if tag.lower() not in inner.lower():
                inner += "," + tag
        return "<FETCH>" + inner + "</FETCH>"

    new, n = re.subn(r"<FETCH>(.*?)</FETCH>", fix_fetch, src, flags=re.S)
    if n:
        (ok if new != src else ok).append("FETCH tags")
        src = new
    else:
        skip.append("FETCH tags")

    # -- mobile parsing ----------------------------------------------------
    MOBILE_NEW = '''                def _d10(v):
                    if not v:
                        return ""
                    d = re.sub(r'[^0-9]', '', re.split(r'[/,;&]', str(v))[0])
                    return d[-10:] if len(d) >= 10 else ""

                mobile = ""
                _fallback = ""
                for _cl in led.findall(".//LEDGERCONTACTLIST.LIST"):
                    _cn = (_cl.findtext("NAME", "") or "").lower()
                    _ph = _d10(_cl.findtext("PHONENUMBER", "") or _cl.findtext("MOBILENO", ""))
                    if not _ph:
                        continue
                    if "mobile" in _cn:
                        mobile = _ph
                        break
                    _fallback = _fallback or _ph
                if not mobile:
                    mobile = (_d10(led.findtext("LEDGERMOBILE", "")) or
                              _d10(led.findtext("MOBILENO", "")) or
                              _d10(led.findtext("PHONENUMBER", "")) or
                              _fallback)'''
    if "LEDGERCONTACTLIST.LIST" in src:
        ok.append("mobile parsing (already present)")
    else:
        src = sub_once(
            src,
            r"[ \t]*_mob_raw\s*=.*?\n(?:.*?\n)*?[ \t]*mobile\s*=\s*\"\"\s*\n",
            MOBILE_NEW + "\n",
            "mobile parsing",
        )

    # -- agency / agent UDF ------------------------------------------------
    UDF_NEW = '''                def _udf(suffix):
                    for _ch in led.iter():
                        if _ch.tag.upper().replace(":", "_").endswith(suffix) \\
                                and _ch.text and _ch.text.strip():
                            return _ch.text.strip()
                    return ""

                agency_nm  = _udf("BMSTLEDAGENCYNAMEUDF")
                agent_nm   = _udf("BEIBROKERNAMEUDF")
                agency_mob = _udf("BGRPBROKERGROUPMOUDF")'''
    if "_udf(" in src:
        ok.append("agency UDF parsing (already present)")
    else:
        src = sub_once(
            src,
            r"[ \t]*agency_nm\s*=\s*led\.findtext\([^\n]*\n"
            r"[ \t]*agent_nm\s*=\s*led\.findtext\([^\n]*\n"
            r"[ \t]*agency_mob\s*=\s*led\.findtext\([^\n]*\n",
            UDF_NEW + "\n",
            "agency UDF parsing",
        )

    save(ENGINE, src)

# ----------------------------------------------------------- scheduler
SCHED = "auto_sync_scheduler.py"
s2 = load(SCHED)
if s2:
    print(f"\n[2/2] {SCHED}")
    backup(SCHED)
    if "tally_alive" in s2:
        ok.append("scheduler guard (already present)")
    else:
        if "from tally_guard import tally_alive" not in s2:
            s2 = "from tally_guard import tally_alive\n" + s2
        s2 = sub_once(
            s2,
            r"(?<![\w.])run_full_sync\(\s*\)",
            "(tally_alive() and run_full_sync()) or "
            "print('Tally offline - sync skipped, data preserved')",
            "scheduler guard",
            flags=0,
        )
        # the lambda-safe form above keeps one-liners working; if the call was
        # not found, user patches manually.
    save(SCHED, s2)

# ----------------------------------------------------------------- report
print("\n================ RESULT ================")
for i in ok:
    print("  OK   ", i)
for i in skip:
    print("  SKIP ", i, "  <-- patch this one by hand (see PATCH_STEPS.md)")
print("========================================")
print("Now run:  venv\\Scripts\\python.exe -c \"import sync_engine, auto_sync_scheduler\"")
sys.exit(1 if skip else 0)
