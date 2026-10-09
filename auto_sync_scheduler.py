from tally_guard import tally_alive
# ============================================================
# auto_sync_scheduler.py  -  Scheduled Tally sync + email reminders
# Run: venv\Scripts\python.exe auto_sync_scheduler.py
# ============================================================
import schedule
import time
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# ALL REMINDERS GO TO THIS EMAIL ONLY (testing mode)
# Change to client email later when ready
# ============================================================
ADMIN_EMAIL = "info@awelion.com"


# ------------------------------------------------------------------
# JOB 1 - Morning: Sync + Outstanding Reminders to Admin
# ------------------------------------------------------------------
def morning_job():
    logger.info("=" * 50)
    logger.info("MORNING JOB STARTED")
    logger.info("=" * 50)

    # Step 1: Sync Tally
    try:
        from sync_engine import run_full_sync
        results = (tally_alive() and run_full_sync()) or print('Tally offline - sync skipped, data preserved')
        logger.info(f"Sync done: {results}")
    except Exception as e:
        logger.error(f"Sync failed: {e}")

    # Step 2: Send outstanding reminders to admin email
    try:
        from db import query_df
        from modules.emailer import send_outstanding_reminder

        df = query_df("""
            SELECT
                o.party_name,
                o.balance,
                sm.salesperson,
                sm.mobile
            FROM outstanding o
            LEFT JOIN salesperson_mapping sm ON sm.party_name = o.party_name
            WHERE o.balance > 0
            ORDER BY o.balance ASC
            LIMIT 50
        """)

        if df.empty:
            logger.info("No outstanding parties found.")
            return

        # Build summary for admin
        total     = float(df["balance"].sum())
        count     = len(df)
        top10     = df.head(10)

        # Build HTML table of top parties
        rows_html = ""
        for _, row in top10.iterrows():
            rows_html += f"""
            <tr>
                <td style="padding:8px;border:1px solid #ddd;">{row['party_name']}</td>
                <td style="padding:8px;border:1px solid #ddd;">{row['salesperson'] or 'Unassigned'}</td>
                <td style="padding:8px;border:1px solid #ddd;color:#c62828;">
                    <strong>Rs.{float(row['balance']):,.2f}</strong>
                </td>
            </tr>"""

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;">
        <div style="max-width:700px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
          <div style="background:#1a237e;color:white;padding:20px;">
            <h2 style="margin:0;">Daily Outstanding Summary</h2>
            <p style="margin:4px 0 0 0;">{datetime.now().strftime('%d %b %Y - %I:%M %p')}</p>
          </div>
          <div style="padding:24px;">
            <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
              <tr>
                <td style="padding:12px;background:#e8eaf6;border-radius:6px;text-align:center;">
                  <div style="font-size:28px;font-weight:bold;color:#1a237e;">
                    Rs.{total:,.2f}
                  </div>
                  <div style="color:#666;">Total Outstanding</div>
                </td>
                <td style="width:20px;"></td>
                <td style="padding:12px;background:#fce4ec;border-radius:6px;text-align:center;">
                  <div style="font-size:28px;font-weight:bold;color:#c62828;">{count}</div>
                  <div style="color:#666;">Total Parties</div>
                </td>
              </tr>
            </table>

            <h3>Top 10 Outstanding Parties</h3>
            <table style="width:100%;border-collapse:collapse;">
              <tr style="background:#1a237e;color:white;">
                <th style="padding:10px;text-align:left;">Party Name</th>
                <th style="padding:10px;text-align:left;">Salesperson</th>
                <th style="padding:10px;text-align:left;">Outstanding</th>
              </tr>
              {rows_html}
            </table>

            <p style="margin-top:20px;color:#888;font-size:13px;">
                This is an automated morning summary from Tally Recovery ERP.<br>
                Login to ERP for full details.
            </p>
          </div>
        </div>
        </body></html>
        """

        from modules.emailer import send_email
        result = send_email(
            to_email=ADMIN_EMAIL,
            subject=f"[Tally ERP] Daily Outstanding Summary - Rs.{total:,.0f} | {count} Parties | {datetime.now().strftime('%d %b %Y')}",
            body_html=html
        )

        if result["success"]:
            logger.info(f"Morning summary email sent to {ADMIN_EMAIL}")
        else:
            logger.error(f"Morning email failed: {result['error']}")

    except Exception as e:
        logger.error(f"Morning email job failed: {e}")


# ------------------------------------------------------------------
# JOB 2 - Afternoon: Sync + Today's Follow-up Reminders to Admin
# ------------------------------------------------------------------
def afternoon_job():
    logger.info("=" * 50)
    logger.info("AFTERNOON JOB STARTED")
    logger.info("=" * 50)

    # Step 1: Sync Tally
    try:
        from sync_engine import run_full_sync
        results = run_full_sync()
        logger.info(f"Sync done: {results}")
    except Exception as e:
        logger.error(f"Sync failed: {e}")

    # Step 2: Send today's follow-up list to admin
    try:
        from db import query_df
        from modules.emailer import send_email

        df = query_df("""
            SELECT
                f.party_name,
                f.next_followup_date,
                f.promise_amount,
                f.notes,
                f.assigned_to,
                f.status,
                f.priority,
                o.balance
            FROM followups f
            LEFT JOIN outstanding o ON o.party_name = f.party_name
            WHERE f.next_followup_date = CURRENT_DATE
              AND f.status NOT IN ('Paid', 'Dispute')
            ORDER BY f.priority DESC
        """)

        if df.empty:
            logger.info("No follow-ups due today.")
            # Still send a "nothing due today" email
            result = send_email(
                to_email=ADMIN_EMAIL,
                subject=f"[Tally ERP] No Follow-ups Due Today - {datetime.now().strftime('%d %b %Y')}",
                body_html=f"""
                <html><body style="font-family:Arial,sans-serif;">
                <div style="max-width:600px;margin:auto;padding:30px;border:1px solid #ddd;border-radius:8px;">
                  <h2 style="color:#1a237e;">Follow-up Summary</h2>
                  <p style="color:#388e3c;font-size:18px;">
                    No follow-ups are scheduled for today ({datetime.now().strftime('%d %b %Y')}).
                  </p>
                </div>
                </body></html>
                """
            )
            return

        # Build HTML table
        priority_colors = {"High": "#ffcccc", "Medium": "#fff3cd", "Low": "#d4edda"}
        rows_html = ""
        for _, row in df.iterrows():
            bg = priority_colors.get(row["priority"], "#fff")
            rows_html += f"""
            <tr style="background:{bg};">
                <td style="padding:8px;border:1px solid #ddd;">{row['party_name']}</td>
                <td style="padding:8px;border:1px solid #ddd;">{row['assigned_to'] or '-'}</td>
                <td style="padding:8px;border:1px solid #ddd;">{row['priority']}</td>
                <td style="padding:8px;border:1px solid #ddd;">{row['status']}</td>
                <td style="padding:8px;border:1px solid #ddd;">
                    Rs.{float(row['balance'] or 0):,.2f}
                </td>
                <td style="padding:8px;border:1px solid #ddd;">
                    Rs.{float(row['promise_amount'] or 0):,.2f}
                </td>
                <td style="padding:8px;border:1px solid #ddd;">{row['notes'] or '-'}</td>
            </tr>"""

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;">
        <div style="max-width:800px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
          <div style="background:#e65100;color:white;padding:20px;">
            <h2 style="margin:0;">Today's Follow-up Reminders</h2>
            <p style="margin:4px 0 0 0;">{datetime.now().strftime('%d %b %Y - %I:%M %p')}</p>
          </div>
          <div style="padding:24px;">
            <p><strong>{len(df)} follow-up(s)</strong> are due today.</p>
            <table style="width:100%;border-collapse:collapse;">
              <tr style="background:#e65100;color:white;">
                <th style="padding:10px;text-align:left;">Party</th>
                <th style="padding:10px;text-align:left;">Assigned To</th>
                <th style="padding:10px;text-align:left;">Priority</th>
                <th style="padding:10px;text-align:left;">Status</th>
                <th style="padding:10px;text-align:left;">Outstanding</th>
                <th style="padding:10px;text-align:left;">Promise Amt</th>
                <th style="padding:10px;text-align:left;">Notes</th>
              </tr>
              {rows_html}
            </table>
            <p style="margin-top:20px;color:#888;font-size:13px;">
                Automated afternoon reminder from Tally Recovery ERP.
            </p>
          </div>
        </div>
        </body></html>
        """

        result = send_email(
            to_email=ADMIN_EMAIL,
            subject=f"[Tally ERP] {len(df)} Follow-up(s) Due Today - {datetime.now().strftime('%d %b %Y')}",
            body_html=html
        )

        if result["success"]:
            logger.info(f"Afternoon follow-up email sent to {ADMIN_EMAIL}")
        else:
            logger.error(f"Afternoon email failed: {result['error']}")

    except Exception as e:
        logger.error(f"Afternoon email job failed: {e}")


# ------------------------------------------------------------------
# Schedule
# ------------------------------------------------------------------
schedule.every().day.at("09:00").do(morning_job)
schedule.every().day.at("16:00").do(afternoon_job)

logger.info("Auto Sync Scheduler started.")
logger.info(f"All reminders sending to: {ADMIN_EMAIL}")
logger.info("09:00 - Tally sync + daily outstanding summary email")
logger.info("16:00 - Tally sync + today's follow-up reminders email")
logger.info("Waiting for scheduled times...")

if __name__ == "__main__":
    while True:
        schedule.run_pending()
        time.sleep(30)
