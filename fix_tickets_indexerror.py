with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    lines = f.readlines()

# Find line with MAIN_SQL definition and check for %% issue
for i, line in enumerate(lines[335:360], start=336):
    if '%%' in line:
        print(f"Line {i}: {line.rstrip()}")

# The fix - MAIN_SQL uses r""" raw string but %% needs to stay %% for psycopg2
# but when used with extra params like (un,) the %% becomes % which causes IndexError
# Fix: replace %% with % in the MAIN_SQL since it's a raw string
print("\nChecking MAIN_SQL definition...")
idx = ''.join(lines).find("MAIN_SQL = r\"\"\"")
if idx > 0:
    print("MAIN_SQL uses raw string - %% should be %%%%")
else:
    print("MAIN_SQL not raw string")
    idx2 = ''.join(lines).find("MAIN_SQL = \"\"\"")
    print(f"Found at: {idx2}")
