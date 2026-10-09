with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    lines = f.readlines()

print("Lines 349-360:")
for i in range(348, 360):
    print(f"{i+1}: {lines[i].rstrip()}")

# Fix line 355 - add LEFT JOIN back
if lines[354].strip().startswith("SELECT"):
    lines[354] = "        LEFT JOIN (\n" + lines[354]
    print("\nFixed line 355")

import ast
code = ''.join(lines)
try:
    ast.parse(code)
    with open(r"flask_app\routes\tickets.py","w",encoding="utf-8") as f:
        f.write(code)
    print("Saved!")
except SyntaxError as e:
    print(f"ERROR line {e.lineno}: {e.msg}")
    for i in range(max(0,e.lineno-3), min(len(lines),e.lineno+2)):
        print(f"{i+1}: {lines[i].rstrip()}")
