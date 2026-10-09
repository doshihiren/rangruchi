import psycopg2
DB = dict(host="localhost",port=5432,dbname="tally_erp",user="postgres",password="7sW9U0JRHzvxrYkLe9kr")
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# 1. RADHE RADHE duplicates in tickets
print("=== RADHE RADHE duplicates ===")
cur.execute("SELECT party_name, net_due FROM tickets WHERE party_name ILIKE '%RADHE RADHE%' ORDER BY party_name")
for r in cur.fetchall():
    print(f"  {r[0]} | net={float(r[1] or 0):,.0f}")

# 2. R P PATEL mobile
print("\n=== R P PATEL mobile ===")
cur.execute("SELECT party_name, party_mobile FROM tickets WHERE party_name ILIKE '%R P PATEL%' OR party_name ILIKE '%RP PATEL%'")
for r in cur.fetchall():
    print(f"  {r[0]} | mobile={r[1]}")
cur.execute("SELECT party_name, mobile FROM tally_party_master WHERE party_name ILIKE '%R P PATEL%' OR party_name ILIKE '%RP PATEL%'")
for r in cur.fetchall():
    print(f"  TPM: {r[0]} | mobile={r[1]}")

# 3. MEM SAAB agency
print("\n=== MEM SAAB agency ===")
cur.execute("SELECT party_name, agency_name FROM tickets WHERE party_name ILIKE '%MEM SAAB%'")
for r in cur.fetchall():
    print(f"  {r[0]} | agency={r[1]}")

# 4. JANKI COLLECTION DUMKA
print("\n=== JANKI COLLECTION ===")
cur.execute("SELECT party_name, agency_name FROM tickets WHERE party_name ILIKE '%JANKI%'")
for r in cur.fetchall():
    print(f"  {r[0]} | agency={r[1]}")

cur.close()
conn.close()
