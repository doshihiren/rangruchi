import ast

with open("sync_tally_master.py","r",encoding="utf-8") as f:
    code = f.read()

# Find where agency mobile is stored
idx = code.find('BGRPBROKERGROUPMOUDF')
print("Agency mobile in sync_tally_master:")
print(code[max(0,idx-100):idx+300])
