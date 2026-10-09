with open(r"flask_app\routes\tickets.py","r",encoding="utf-8") as f:
    lines = f.readlines()

# Show lines 330-360
for i, line in enumerate(lines[325:365], start=326):
    print(f"{i}: {line.rstrip()}")
