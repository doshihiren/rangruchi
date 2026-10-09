with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    lines = f.readlines()

# Find MAIN_SQL line
for i,l in enumerate(lines):
    if 'MAIN_SQL = r"""' in l:
        print(f"Found MAIN_SQL at line {i+1}")
        lines[i] = lines[i].replace('MAIN_SQL = r"""', 'MAIN_SQL = """')
        print("Changed r\"\"\" to \"\"\"")
        break

# Now find the LATERAL % and change to %%
for i,l in enumerate(lines):
    if "|| '%'" in l and 'LATERAL' in ''.join(lines[max(0,i-5):i+1]):
        print(f"Line {i+1}: {l.rstrip()}")
        lines[i] = l.replace("|| '%'", "|| '%%'")
        print(f"Fixed: {lines[i].rstrip()}")

import ast
code = ''.join(lines)
try:
    ast.parse(code)
    with open(r"flask_app\routes\tickets.py","w",encoding="utf-8") as f:
        f.write(code)
    print("Saved!")
except SyntaxError as e:
    print(f"ERROR {e.lineno}: {e.msg}")
