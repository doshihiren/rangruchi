# ============================================================
# run_flask.py  -  Start Flask from project root
# Run: venv\Scripts\python.exe run_flask.py
# ============================================================
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from flask_app import create_app

app = create_app()

if __name__ == "__main__":
    print("\n  RecoveryOS Flask is running!")
    print("  Open: http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
