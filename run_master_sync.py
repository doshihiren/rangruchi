import sys
sys.argv = ['sync_tally_master.py', 'Master.xml']
from sync_tally_master import sync_party_master, sync_agency_fullnames
sync_party_master("Master.xml")
sync_agency_fullnames()
print("Done")
