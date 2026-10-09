with open("sync_engine.py","r",encoding="utf-8") as f:
    code = f.read()

import re
# Find mobile parsing in sync_ledger_masters
idx = code.find("def sync_ledger_masters")
func_end = code.find("\ndef ", idx+5)
func = code[idx:func_end]

# Find mobile tag
for tag in ['MOBILE','mobile','PHONENUMBER','PHONE','LEDGERMOBILE']:
    i = func.find(tag)
    if i > 0:
        print(f"Tag '{tag}' at {i}:")
        print(func[max(0,i-50):i+150])
        print()
