import re, html

with open("Master.xml","rb") as f: raw = f.read()
try: text = raw.decode("utf-16-le", errors="ignore")
except: text = raw.decode("utf-8", errors="ignore")

# Search exact name
idx = text.find('SUPER KIDS WEAR (WAGHOLI)')
print(f"Found at index: {idx}")
if idx > 0:
    print(text[max(0,idx-20):idx+500])
else:
    print("NOT FOUND in current Master.xml")
    print("Master.xml needs to be re-exported from Tally")
