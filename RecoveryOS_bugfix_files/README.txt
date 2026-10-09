RecoveryOS replacement pack
1. Copy routes/*.py -> flask_app/routes/
2. Copy templates/*.html -> flask_app/templates/
3. Copy sync_engine.py -> project root
4. Restart Flask
5. Run full Tally sync (Admin Sync or python sync_engine.py)

Included fixes:
- PDC: INSTRUMENTDATE as cheque date + INSTRUMENTNUMBER + settled invoices from BILLALLOCATIONS/<NAME>
- Credit period syncs from Tally BILLCREDITPERIOD on every full sync into tickets.credit_days then net_due recalculated
- Tickets: hide parties where COALESCE(net_due,0)=0
- Followups: hide parties where COALESCE(net_due,0)=0 (and auto-archive on sync)