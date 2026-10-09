with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    code = f.read()

print("LATERAL in file:", "LATERAL" in code)
print("sm_agency_phone:", "sm_agency_phone" in code)

# Find agency_phone column in SELECT
idx = code.find("sm_agency_phone")
print("\nColumn name:")
print(code[max(0,idx-50):idx+50])

# Find what template uses
idx2 = code.find("agency_phone")
print("\nAll agency_phone refs:")
for i, line in enumerate(code.split('\n')):
    if 'agency_phone' in line or 'sm_agency_phone' in line:
        print(f"  line {i+1}: {line.strip()[:80]}")
