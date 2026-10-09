from db import fetchone

row = fetchone("""
    SELECT
        COUNT(*) AS total_parties,
        COUNT(NULLIF(mobile, '')) AS with_mobile,
        COUNT(NULLIF(agency_name, '')) AS with_agency
    FROM tally_party_master
""")

print("Total parties:", row["total_parties"])
print("With mobile:  ", row["with_mobile"])
print("With agency:  ", row["with_agency"])
