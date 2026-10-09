import ast

with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    code = f.read()

# Change tam JOIN to use DISTINCT ON to prevent duplicates while using LIKE
idx = code.find("tally_agency_master tam")
print("Current JOIN:")
print(repr(code[idx:idx+250]))
