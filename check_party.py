from db import fetchone

party = "SK MART (SECUNDERABAD)"

print("Checking party:", party)

master = fetchone("""
    SELECT party_name, mobile, agency_name
    FROM tally_party_master
    WHERE UPPER(TRIM(party_name)) = UPPER(TRIM(%s))
""", (party,))

print("\n=== TALLY PARTY MASTER ===")
if master:
    print("Party name:", master["party_name"])
    print("Mobile:    ", master["mobile"])
    print("Agency:    ", master["agency_name"])
else:
    print("Party not found in tally_party_master")

ticket = fetchone("""
    SELECT *
    FROM tickets
    WHERE UPPER(TRIM(party_name)) = UPPER(TRIM(%s))
    LIMIT 1
""", (party,))

print("\n=== TICKETS SAMPLE ===")
if ticket:
    print(ticket)
else:
    print("No ticket found for this party")
